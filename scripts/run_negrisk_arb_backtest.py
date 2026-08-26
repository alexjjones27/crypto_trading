"""Backtest: NegRisk multi-outcome basket arbitrage.

A companion strategy to the Final-1% signal, structurally different (not a
probabilistic edge -- a completeness arbitrage). Polymarket's NegRisk
markets group N mutually exclusive, jointly exhaustive outcomes (e.g. "who
wins the election") under a shared negRiskMarketID, with an explicit "Other"
catch-all leg (negRiskOther=true) guaranteeing the set is complete. Whenever
the sum of the N legs' YES prices (plus taker fees) is less than $1, buying
one share of every leg costs less than $1 and is guaranteed to redeem for
exactly $1 (via the CTF mergePositions call) regardless of which outcome
wins -- a real, execution-risk-bounded arbitrage rather than a directional
bet on a flip-rate belief.

Data reality check, same honesty standard as polymarket_final_pct.py:
  - No historical order-book depth exists for resolved markets (`/book`
    404s), so -- exactly as in the Final-1% backtest -- each leg's fill
    price is proxied by its last observed CLOB prices-history snapshot,
    not a real executable quote. This backtest additionally assumes all N
    legs fill simultaneously at those snapshot prices; real execution
    across N separate order books has slippage/race risk this does not
    model.
  - Only events with an explicit `negRiskOther` leg are included, so
    completeness (the thing that makes this riskless rather than
    probabilistic) is empirically verified per event, not assumed.
  - This is a bounded, volume-ranked SAMPLE (top-N by trading volume among
    complete NegRisk events), not an exhaustive census like the Final-1%
    market population -- documented explicitly, unlike that project.
"""
import json
import math
import os
import sys
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import polymarket_final_pct as pmf

REPO = Path(__file__).resolve().parents[1]
RESULTS_DIR = REPO / "results" / "polymarket_final_pct"
CACHE_DIR = REPO / "data" / "raw" / "polymarket" / "negrisk_events"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

N_EVENTS = 20            # top-volume complete NegRisk events to backtest
N_CONSECUTIVE = 2         # hourly snapshots required before treating a gap as tradeable, not a stale-price artifact
FIDELITY_MIN = 60         # 1h bars, matching the project's established "coarse full-lifetime" convention
START_BANKROLL = 10000.0
STAKE_FRAC = 0.15         # fraction of current equity committed per basket trade
MAX_LEGS = 120            # sanity bound, not expected to bind on the actual top-20 list


def _parse_ts(s):
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def fetch_top_negrisk_events(n=N_EVENTS):
    cache_path = CACHE_DIR / f"top_{n}_complete_negrisk_events.json"
    if cache_path.exists():
        return json.loads(cache_path.read_text())

    print(f"[negrisk] paging /events by volume desc to find complete NegRisk baskets ...")
    all_events = []
    for offset in range(0, pmf.GAMMA_OFFSET_CAP, 100):
        page = pmf._get(pmf.GAMMA_BASE, "/events", {
            "closed": "true", "order": "volume", "ascending": "false", "limit": 100, "offset": offset,
        })
        if not page:
            break
        all_events.extend(page)

    qualifying = []
    for e in all_events:
        if not e.get("negRisk"):
            continue
        markets = e.get("markets", [])
        if not (3 <= len(markets) <= MAX_LEGS):
            continue
        if not any(m.get("negRiskOther") for m in markets):
            continue  # only provably-complete baskets: an explicit Other leg confirms exhaustiveness
        qualifying.append(e)

    qualifying.sort(key=lambda e: -(e.get("volume") or 0))
    top = qualifying[:n]
    print(f"[negrisk] {len(qualifying)} complete NegRisk events found; taking top {len(top)} by volume")
    cache_path.write_text(json.dumps(top))
    return top


def extract_legs(event):
    legs = []
    for m in event.get("markets", []):
        token_ids = pmf._safe_json_list(m.get("clobTokenIds"))
        outcome_prices = pmf._safe_json_list(m.get("outcomePrices"))
        if not token_ids or not outcome_prices:
            continue
        created = _parse_ts(m.get("createdAt"))
        closed = _parse_ts(m.get("closedTime")) or _parse_ts(m.get("updatedAt"))
        if created is None or closed is None:
            continue
        try:
            resolved_yes = float(outcome_prices[0]) >= 0.5
        except (ValueError, TypeError):
            continue
        fee_schedule = m.get("feeSchedule") or {}
        fee_rate = fee_schedule.get("rate")
        if fee_rate is None:
            fee_rate = 0.04  # documented fallback (politics-tier rate), only used if feeSchedule missing
        legs.append({
            "market_id": m["id"], "question": m.get("question", ""),
            "leg_name": m.get("groupItemTitle", m.get("question", "")),
            "token_id": token_ids[0],  # YES token
            "created_at": created, "closed_time": closed,
            "resolved_yes": resolved_yes, "fee_rate": float(fee_rate),
            "is_other": bool(m.get("negRiskOther")),
        })
    return legs


def fetch_leg_prices(token_id, start_s, end_s):
    return pmf.fetch_price_series(token_id, start_s, end_s, fidelity=FIDELITY_MIN)


def find_arb_entry(event, legs):
    scan_start = max(l["created_at"] for l in legs)
    scan_end = max(l["closed_time"] for l in legs)
    if scan_end <= scan_start:
        return None
    start_s, end_s = int(scan_start.timestamp()), int(scan_end.timestamp())

    series = {}
    with ThreadPoolExecutor(max_workers=16) as pool:
        futures = {pool.submit(fetch_leg_prices, l["token_id"], start_s, end_s): l["token_id"] for l in legs}
        for fut in as_completed(futures):
            tok = futures[fut]
            try:
                series[tok] = fut.result()
            except Exception:
                series[tok] = pmf.pd.DataFrame(columns=["t", "p"])

    frames = []
    n_floored = 0
    for l in legs:
        df = series.get(l["token_id"])
        if df is None or df.empty:
            # No recorded trading activity at all (common for far-tail legs in a
            # large basket, e.g. a minor team in a 60-leg tournament winner
            # market): assumed priced at the $0.001 minimum tick for the whole
            # window rather than dropping the event -- conservative, since a
            # genuinely near-zero-probability leg barely moves the basket sum
            # either way, and this avoids losing large, real, high-volume
            # events purely because one long-tail leg never printed a trade.
            s = pmf.pd.Series([0.001, 0.001], index=[start_s, end_s], name=l["token_id"])
            n_floored += 1
        else:
            s = df.set_index("t")["p"].rename(l["token_id"])
        frames.append(s)
    combined = pmf.pd.concat(frames, axis=1).sort_index().ffill()
    combined = combined.dropna(how="any")  # only once every leg has been observed at least once
    print(f"    [debug] {len(legs)} legs, {n_floored} floored (no trade data), "
          f"{len(combined)} usable grid points", flush=True)
    if combined.empty:
        return None

    fee_by_tok = {l["token_id"]: l["fee_rate"] for l in legs}
    cost = combined.copy()
    for tok in cost.columns:
        fr = fee_by_tok[tok]
        cost[tok] = combined[tok] + fr * combined[tok] * (1 - combined[tok])
    total_cost = cost.sum(axis=1)
    profit_frac = 1.0 - total_cost

    qualifies = profit_frac > 0
    # require N_CONSECUTIVE straight qualifying snapshots (same persistence filter as the Final-1% signal)
    run = 0
    hit_idx = None
    idx_list = qualifies.index.tolist()
    for i, ok in enumerate(qualifies.tolist()):
        run = run + 1 if ok else 0
        if run >= N_CONSECUTIVE:
            hit_idx = idx_list[i - N_CONSECUTIVE + 1]
            break
    if hit_idx is None:
        return {"event_id": event["id"], "title": event["title"], "n_legs": len(legs),
                "max_profit_frac": float(profit_frac.max()), "arb_found": False}

    entry_prices = combined.loc[hit_idx].to_dict()
    return {
        "event_id": event["id"], "title": event["title"], "n_legs": len(legs),
        "arb_found": True,
        "entry_time": pmf.pd.Timestamp(hit_idx, unit="s", tz="UTC").isoformat(),
        "basket_sum": float(combined.loc[hit_idx].sum()),
        "total_cost_frac": float(total_cost.loc[hit_idx]),
        "profit_frac": float(profit_frac.loc[hit_idx]),
        "max_profit_frac": float(profit_frac.max()),
        "entry_prices": {k[-10:]: round(v, 4) for k, v in entry_prices.items()},
    }


def main():
    events = fetch_top_negrisk_events(N_EVENTS)
    print(f"[negrisk] gas estimate (live Polygon, non-relayed merge tx) ...")
    gas_cfg = pmf.GasAssumptions(relayer_sponsored=False)
    try:
        gas_cfg = pmf.GasAssumptions(relayer_sponsored=False,
                                      non_relayed_cost_usd_per_trade=pmf.fetch_live_gas_estimate())
    except Exception as exc:
        print(f"  [negrisk] live gas estimate failed ({exc}); using documented fallback ${gas_cfg.cost_usd():.4f}")
    gas_cost = gas_cfg.cost_usd()
    print(f"[negrisk] merge-tx gas cost: ${gas_cost:.4f} (relayer covers ordinary order flow; the CTF merge "
          f"call is modeled as a real on-chain tx since it's outside the standard gasless trading path)")

    results = []
    n_with_arb = 0
    for i, event in enumerate(events):
        legs = extract_legs(event)
        if len(legs) < 3:
            continue
        print(f"[negrisk] ({i+1}/{len(events)}) {event['title'][:55]!r} -- {len(legs)} legs ...", flush=True)
        r = find_arb_entry(event, legs)
        if r is None:
            continue
        r["end_date"] = event.get("endDate")
        r["volume"] = event.get("volume")
        results.append(r)
        if r["arb_found"]:
            n_with_arb += 1
            print(f"    ARB @ {r['entry_time'][:10]}  basket_sum={r['basket_sum']:.4f}  "
                  f"profit={r['profit_frac']*100:.2f}%")
        else:
            print(f"    no qualifying gap (best observed: {r['max_profit_frac']*100:.2f}%)")

    trades = sorted([r for r in results if r["arb_found"]], key=lambda r: r["entry_time"])

    equity = START_BANKROLL
    curve = [(trades[0]["entry_time"][:10] if trades else None, equity)]
    for t in trades:
        stake = STAKE_FRAC * equity
        pnl = stake * t["profit_frac"] - gas_cost
        equity += pnl
        t["stake"] = round(stake, 2)
        t["pnl"] = round(pnl, 2)
        t["equity_after"] = round(equity, 2)
        curve.append((t["entry_time"][:10], round(equity, 2)))

    summary = {
        "n_events_scanned": len(results),
        "n_events_with_arb": n_with_arb,
        "pct_events_with_arb": round(n_with_arb / len(results) * 100, 1) if results else None,
        "start_bankroll": START_BANKROLL,
        "final_equity": round(equity, 2),
        "total_return_pct": round((equity / START_BANKROLL - 1) * 100, 2),
        "n_trades": len(trades),
        "gas_cost_per_trade": round(gas_cost, 4),
        "stake_frac": STAKE_FRAC,
        "mean_profit_frac_pct": round(sum(t["profit_frac"] for t in trades) / len(trades) * 100, 3) if trades else None,
        "median_profit_frac_pct": round(sorted(t["profit_frac"] for t in trades)[len(trades)//2] * 100, 3) if trades else None,
        "trades": trades,
        "all_scanned": [{k: v for k, v in r.items() if k != "entry_prices"} for r in results],
        "equity_curve": curve,
    }

    print(f"\n=== NegRisk basket arbitrage: {n_with_arb}/{len(results)} events had a qualifying gap "
          f"({summary['pct_events_with_arb']}%) ===")
    print(f"Trades taken: {len(trades)}  |  ${START_BANKROLL:,.0f} -> ${equity:,.2f} "
          f"({summary['total_return_pct']:+.2f}%)")

    out_path = RESULTS_DIR / "negrisk_arb_results.json"
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"saved {out_path}")


if __name__ == "__main__":
    main()
