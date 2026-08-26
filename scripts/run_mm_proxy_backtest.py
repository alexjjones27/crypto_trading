"""Stylized market-making PnL estimate -- NOT a real backtest.

Real market-making can't be rigorously backtested here: Polymarket's `/book`
endpoint 404s on resolved markets (confirmed live, see
polymarket_final_pct.py), so there is no historical order-book depth to
determine what price a resting quote would actually have been filled at, or
how often. This script instead builds an explicitly toy, parameterized
estimate from the one thing that *is* recoverable historically -- the
public trade-print tape (data-api /trades) -- and states its assumptions as
assumptions, not measurements.

Model: for a fixed assumed half-spread and an assumed "fill share" (the
fraction of each real trade's size a resting maker quote is assumed to
capture), every captured unit is priced at the trade print improved by the
half-spread, and held to the market's resolution (no active inventory
hedging modeled -- unrealistic in the conservative direction, since a real
MM skews quotes to manage inventory, so this likely overstates the model's
own directional risk rather than understating it). Per captured share:
  taker BUY (MM sells)  -> pnl = (price + half_spread) - resolved_payout
  taker SELL (MM buys)  -> pnl = resolved_payout - (price - half_spread)
Summed across all captured units, this is algebraically spread-capture plus
whatever net directional inventory imbalance the trade flow left behind --
no order-book simulation, no queue-position modeling, no real fill
probability. Run as a sensitivity grid over (half_spread, fill_share), not
a single point estimate, precisely because both are assumptions.

Reuses the SAME market population and (already disk-cached, no new network
calls) trade tapes as the Final-1% backtest, via fetch_market_trades.
"""
import csv
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import polymarket_final_pct as pmf

REPO = Path(__file__).resolve().parents[1]
RESULTS_DIR = REPO / "results" / "polymarket_final_pct"

START_BANKROLL = 10000.0
MAX_NOTIONAL_PER_TRADE = 25.0  # caps a single captured trade's size, so one whale print can't dominate

HALF_SPREADS = [0.005, 0.01, 0.02]
FILL_SHARES = [0.05, 0.15, 0.30]
BASE_HALF_SPREAD = 0.01
BASE_FILL_SHARE = 0.15


def load_market_meta():
    """cid -> {resolved_outcome_index, resolution_time}, from the existing
    Final-1% trade sample (same population, zero extra fetches)."""
    meta = {}
    with open(RESULTS_DIR / "trades_maker.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            cid = r["condition_id"]
            if cid in meta:
                continue
            meta[cid] = {
                "resolved_outcome_index": int(r["resolved_outcome_index"]) if r["resolved_outcome_index"] not in ("", None) else None,
                "resolution_time": r["resolution_time"],
                "question": r["question"],
            }
    return meta


def market_pnl(trades, resolved_idx, half_spread, fill_share):
    total = 0.0
    n_captured = 0
    captured_notional = 0.0
    for t in trades:
        try:
            price = float(t["price"])
            size = float(t["size"])
            side = t["side"]
            outcome_idx = int(t.get("outcomeIndex", 0))
        except (KeyError, ValueError, TypeError):
            continue
        if price <= 0 or price >= 1 or size <= 0:
            continue
        shares = min(size * fill_share, MAX_NOTIONAL_PER_TRADE / price)
        if shares <= 0:
            continue
        resolved_payout = 1.0 if outcome_idx == resolved_idx else 0.0
        if side == "BUY":
            per_share = (price + half_spread) - resolved_payout
        elif side == "SELL":
            per_share = resolved_payout - (price - half_spread)
        else:
            continue
        total += shares * per_share
        n_captured += 1
        captured_notional += shares * price
    return total, n_captured, captured_notional


def main():
    meta = load_market_meta()
    print(f"[mm-proxy] {len(meta)} markets in the reused Final-1% population, "
          f"all with cached trade tapes on disk already")

    sensitivity = {}
    for hs in HALF_SPREADS:
        for fs in FILL_SHARES:
            sensitivity[f"hs{hs}_fs{fs}"] = {"half_spread": hs, "fill_share": fs, "total_pnl": 0.0, "n_markets_active": 0}

    per_market_base = []  # for the base-case equity curve
    n_no_resolved_idx = 0
    n_no_trades = 0
    for i, (cid, m) in enumerate(meta.items()):
        if m["resolved_outcome_index"] is None:
            n_no_resolved_idx += 1
            continue
        trades = pmf.fetch_market_trades(cid)
        if not trades:
            n_no_trades += 1
            continue

        for key, cfg in sensitivity.items():
            pnl, n_cap, notional = market_pnl(trades, m["resolved_outcome_index"], cfg["half_spread"], cfg["fill_share"])
            cfg["total_pnl"] += pnl
            if n_cap > 0:
                cfg["n_markets_active"] += 1

        pnl_base, n_cap_base, notional_base = market_pnl(trades, m["resolved_outcome_index"], BASE_HALF_SPREAD, BASE_FILL_SHARE)
        if n_cap_base > 0:
            per_market_base.append({
                "condition_id": cid, "question": m["question"][:80],
                "resolution_time": m["resolution_time"], "pnl": round(pnl_base, 4),
                "n_captured_trades": n_cap_base, "captured_notional": round(notional_base, 2),
            })
        if (i + 1) % 500 == 0:
            print(f"  [mm-proxy] {i+1}/{len(meta)} markets processed ...", flush=True)

    per_market_base.sort(key=lambda r: r["resolution_time"])
    equity = START_BANKROLL
    curve = [(per_market_base[0]["resolution_time"][:10] if per_market_base else None, equity)]
    for r in per_market_base:
        equity += r["pnl"]
        curve.append((r["resolution_time"][:10], round(equity, 2)))

    base_key = f"hs{BASE_HALF_SPREAD}_fs{BASE_FILL_SHARE}"
    base = sensitivity[base_key]

    summary = {
        "n_markets_total": len(meta),
        "n_markets_no_resolution": n_no_resolved_idx,
        "n_markets_no_trades": n_no_trades,
        "n_markets_with_captured_flow_base_case": base["n_markets_active"],
        "start_bankroll": START_BANKROLL,
        "max_notional_per_trade": MAX_NOTIONAL_PER_TRADE,
        "base_case": {"half_spread": BASE_HALF_SPREAD, "fill_share": BASE_FILL_SHARE},
        "final_equity_base_case": round(equity, 2),
        "total_pnl_base_case": round(base["total_pnl"], 2),
        "total_return_pct_base_case": round(base["total_pnl"] / START_BANKROLL * 100, 2),
        "sensitivity_grid": list(sensitivity.values()),
        "equity_curve_base_case": curve,
        "per_market_base_case": per_market_base,
    }

    print(f"\n=== Stylized MM proxy, base case (half_spread=${BASE_HALF_SPREAD}, fill_share={BASE_FILL_SHARE:.0%}) ===")
    print(f"{base['n_markets_active']} of {len(meta)} markets had any captured flow")
    print(f"Cumulative additive PnL: ${base['total_pnl']:,.2f}  ->  ${START_BANKROLL:,.0f} + PnL = ${equity:,.2f} "
          f"({summary['total_return_pct_base_case']:+.2f}%, NOT compounded)")
    print("\nSensitivity grid (total PnL, $):")
    for key, cfg in sensitivity.items():
        print(f"  half_spread=${cfg['half_spread']:<6} fill_share={cfg['fill_share']:<6.0%}  "
              f"total_pnl=${cfg['total_pnl']:>10,.2f}  active_markets={cfg['n_markets_active']}")

    out_path = RESULTS_DIR / "mm_proxy_results.json"
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\nsaved {out_path}")


if __name__ == "__main__":
    main()
