"""Live scan: which currently-open Polymarket markets meet the 70%-threshold
entry criteria right now, and what position size that implies for a given
bankroll.

Read-only. This does not place orders, hold API keys, or touch a wallet --
it only reads Gamma/CLOB public endpoints and prints candidates for you to
act on manually. This is a point-in-time snapshot, not a backtest: run it
fresh each time you want current signals.

Adapted from scan_live_signals.py (the 99% version). Differences:
  - THRESHOLD = 0.70 instead of 0.99.
  - CATEGORY_FLIPS uses the per-bucket flip counts measured directly from
    trades_maker_thr07_v2.csv (post exact-score/weather exclusion), not the
    99%-threshold counts -- flip risk at 0.70 is ~12-15% per bucket, not
    ~0-0.2%, and reusing the 99% prior here would badly understate risk.
  - BANKROLL defaults to whatever you pass on the command line (a live test
    account is likely tiny; the 99% script's $1,000 default doesn't apply).
"""
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import polymarket_final_pct as pmf

BANKROLL = float(sys.argv[1]) if len(sys.argv) > 1 else 5.0
MAX_POS_PCT = 0.03
AGG_CAP_PCT = 0.50
CAT_CAP_PCT = 0.25
THRESHOLD = 0.70
N_CONSECUTIVE = 3
PRIOR_A, PRIOR_B = 1.0, 40.0
# Prior mean = 1/41 = 2.4%, deliberately looser than the 99%-threshold
# script's Beta(1,300) (mean 0.33%) -- that prior was tuned for a ~0.2%
# empirical flip-rate regime and would badly understate risk at 70%, where
# measured flip rates run 12-15% per bucket. This prior still converges to
# the real per-bucket rate quickly (all buckets below have n > 700 except
# politics) but doesn't start out falsely confident.

# Measured directly from trades_maker_thr07_v2.csv, post exact-score/weather
# exclusion (see scripts/run_kelly_backtest.py for the same exclusion regexes).
# (flips, total resolved trades), by report_bucket.
CATEGORY_FLIPS = {
    "crypto_price": (87, 715),
    "sports": (233, 1893),
    "other": (149, 1151),
    "politics": (9, 61),
}


def qh(bucket: str) -> float:
    k, n = CATEGORY_FLIPS.get(bucket, (0, 0))
    return (PRIOR_A + k) / (PRIOR_A + PRIOR_B + n)


def _active_page(date_min, date_max, offset):
    return pmf._get(pmf.GAMMA_BASE, "/markets", {
        "closed": "false", "active": "true", "limit": pmf.GAMMA_PAGE_LIMIT, "offset": offset,
        "end_date_min": date_min, "end_date_max": date_max,
    })


def fetch_active_markets(date_min: str, date_max: str) -> list[dict]:
    out, offset = [], 0
    while True:
        page = _active_page(date_min, date_max, offset)
        if not page:
            break
        out.extend(page)
        if len(page) < pmf.GAMMA_PAGE_LIMIT:
            break
        offset += pmf.GAMMA_PAGE_LIMIT
        if offset > pmf.GAMMA_OFFSET_CAP:
            break
    return out


def fetch_live_book_depth(token_id: str, price_threshold: float) -> float | None:
    try:
        book = pmf._get(pmf.CLOB_BASE, "/book", {"token_id": token_id})
    except Exception:
        return None
    asks = book.get("asks") or []
    total = sum(float(a["size"]) for a in asks if float(a["price"]) <= price_threshold + 0.05)
    return total if asks else None


def check_market(market: dict) -> dict | None:
    token_ids = pmf._safe_json_list(market.get("clobTokenIds"))
    outcomes = pmf._safe_json_list(market.get("outcomes"))
    prices_raw = pmf._safe_json_list(market.get("outcomePrices"))
    if not token_ids or not prices_raw:
        return None
    try:
        prices = [float(p) for p in prices_raw]
    except (ValueError, TypeError):
        return None

    for idx, (tok, p) in enumerate(zip(token_ids, prices)):
        if p < 0.68:  # cheap pre-screen; confirm properly below
            continue
        now_s = int(time.time())
        df, source = pmf.fetch_token_lifetime_prices(tok, now_s - 3 * 86400, now_s + 60)
        if df.empty:
            continue
        hit = pmf.detect_crossing(df, threshold=THRESHOLD, n_consecutive=N_CONSECUTIVE)
        if hit is None:
            continue
        last_price = float(df["p"].iloc[-1])
        if last_price < THRESHOLD:
            continue
        category = pmf.classify_fee_category(market)
        bucket = pmf.classify_report_bucket(market)
        question = market.get("question", "")
        excluded = bool(pmf.re.search(r"^Exact Score:", question, pmf.re.I)) or \
                   bool(pmf.re.search(r"highest temperature.*(be between|be \d)", question, pmf.re.I))

        depth = fetch_live_book_depth(tok, last_price)

        return {
            "market_id": market["id"], "question": question, "outcome": outcomes[idx] if idx < len(outcomes) else None,
            "current_price": last_price, "entry_price_at_crossing": hit["entry_price"],
            "category": category, "report_bucket": bucket, "excluded": excluded,
            "end_date": market.get("endDate"), "volume": market.get("volumeNum"),
            "live_ask_depth_notional": depth,
        }
    return None


def kelly_size(bucket: str, price: float, bankroll: float, fraction: float = 0.25) -> dict:
    b = (1.0 - price) / price  # maker fill, $0 fee
    L = 1.0
    q = qh(bucket)
    p = 1.0 - q
    f_kelly = (p * b - q * L) / (b * L) if b > 0 else 0.0
    desired = max(0.0, f_kelly) * fraction * bankroll
    per_trade_capped = min(desired, MAX_POS_PCT * bankroll)
    return {"flip_belief_q": q, "kelly_fraction_raw": f_kelly, "desired_uncapped": desired,
            "per_trade_capped": per_trade_capped, "margin": p * b - q * L}


def allocate_portfolio(rows: list[dict], bankroll: float) -> list[dict]:
    ranked = sorted(rows, key=lambda r: r["margin"], reverse=True)
    agg_used = 0.0
    cat_used: dict[str, float] = {}
    for r in ranked:
        bucket = r["report_bucket"]
        room_agg = AGG_CAP_PCT * bankroll - agg_used
        room_cat = CAT_CAP_PCT * bankroll - cat_used.get(bucket, 0.0)
        stake = max(0.0, min(r["per_trade_capped"], room_agg, room_cat))
        if r.get("live_ask_depth_notional") is not None:
            stake = min(stake, r["live_ask_depth_notional"])
        r["portfolio_position_size"] = round(stake, 4)
        agg_used += stake
        cat_used[bucket] = cat_used.get(bucket, 0.0) + stake
    return ranked


def main():
    print(f"Bankroll for this scan: ${BANKROLL:.2f}")
    print("Fetching currently active (open) Polymarket markets ...")
    today = pmf.pd.Timestamp.utcnow().strftime("%Y-%m-%d")
    far_future = "2028-01-01"
    markets = fetch_active_markets(today, far_future)
    markets += fetch_active_markets(
        (pmf.pd.Timestamp.utcnow() - pmf.pd.Timedelta(days=1)).strftime("%Y-%m-%d"), today
    )
    markets = pmf._dedupe_by_id(markets)
    markets = [m for m in markets if pmf._safe_json_list(m.get("clobTokenIds"))]
    print(f"  {len(markets):,} active markets with CLOB tokens")

    print(f"Screening for live ${THRESHOLD:.2f}+ signals (checking recent price history for persistence) ...")
    hits = []
    with ThreadPoolExecutor(max_workers=16) as pool:
        futures = {pool.submit(check_market, m): m for m in markets}
        for i, fut in enumerate(as_completed(futures)):
            try:
                r = fut.result()
            except Exception:
                r = None
            if r:
                hits.append(r)
            if (i + 1) % 500 == 0:
                print(f"  scanned {i+1}/{len(markets)} ...", flush=True)

    print(f"\n{len(hits)} markets currently meet the ${THRESHOLD:.2f}/3-consecutive-snapshot entry criteria\n")

    rows = []
    for h in hits:
        if h["excluded"]:
            continue
        sizing = kelly_size(h["report_bucket"], h["current_price"], BANKROLL)
        rows.append({**h, **sizing})

    allocated = allocate_portfolio(rows, BANKROLL)

    print(f"{len(allocated)} tradeable after exact-score/weather exclusion. "
          f"Portfolio-allocated at ${BANKROLL:.2f} bankroll (50% aggregate cap, 25% per-category cap, "
          f"3% per-trade cap, capped further by live ask depth where available):\n")
    total_deployed = 0.0
    n_funded = 0
    for r in allocated:
        if r["portfolio_position_size"] <= 0:
            continue
        n_funded += 1
        total_deployed += r["portfolio_position_size"]
        depth_note = (f"${r['live_ask_depth_notional']:.0f} live depth"
                      if r["live_ask_depth_notional"] is not None else "no book data")
        below_min = "  [likely below Polymarket's min order size -- check the UI]" if r["portfolio_position_size"] < 1.0 else ""
        print(f"- {r['question'][:65]!r} [{r['outcome']}] @ ${r['current_price']:.4f}  ({r['report_bucket']})\n"
              f"    Kelly-implied position: ${r['portfolio_position_size']:.4f}  "
              f"(q={r['flip_belief_q']*100:.2f}%, margin={r['margin']*100:.2f}%, {depth_note}){below_min}")

    print(f"\n{n_funded} positions funded, ${total_deployed:.4f} of ${BANKROLL:.2f} deployed "
          f"({total_deployed/BANKROLL*100:.1f}% of bankroll)")

    out_path = Path(pmf.RESULTS_DIR) / "live_signal_scan_70.json"
    with open(out_path, "w") as f:
        json.dump(allocated, f, indent=2, default=str)
    print(f"saved {out_path}")


if __name__ == "__main__":
    main()
