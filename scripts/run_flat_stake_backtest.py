"""Flat 1%-of-equity sizing on the existing sub-1%-longshot-short population.

The Final-1% trade *is* the "short every sub-1% longshot" backtest: buying
the complementary token once price crosses $0.99+ is economically the same
position as betting against whichever outcome is under $0.01 at that
moment. That population (trades_maker.csv, post-exclusion) already has a
real flip rate measured (3 flips / ~2,367 trades). This script re-runs it
under simple flat position sizing -- every qualifying trade gets exactly
FLAT_FRAC of current equity, no Kelly edge calculation, no per-trade cap --
as a plain, easy-to-reason-about companion to the walk-forward Kelly
version, not a new backtest of a new population.
"""
import json
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_kelly_backtest import load, DATA_DIR, START_BANKROLL

FLAT_FRAC = 0.01
AGG_CAP_PCT = 0.50
CAT_CAP_PCT = 0.25


def run_flat_sim(all_trades, flat_frac=FLAT_FRAC, agg_cap_pct=AGG_CAP_PCT, cat_cap_pct=CAT_CAP_PCT, track_trades=False):
    tradeable = [r for r in all_trades if not r["excluded"]]
    events = []
    for r in tradeable:
        resolve_key_t = max(r["resolve_dt"], r["entry_dt"])
        events.append((r["entry_dt"], 0, "entry", r))
        events.append((resolve_key_t, 1, "resolve", r))
    events.sort(key=lambda e: (e[0], e[1]))

    cash = START_BANKROLL
    committed = {}
    committed_by_bucket = {}
    equity_series = []
    n_taken = 0
    n_skip_capital = 0
    n_flips_taken = 0
    n_wins_taken = 0
    trade_records = []

    for t, order, kind, r in events:
        if kind == "entry":
            bucket = r["report_bucket"]
            price = r["entry_price"]
            L = 1.0 + r["fee_frac"]
            b = (1.0 - price) / price - r["fee_frac"]
            equity = cash + sum(committed.values())
            if b <= 0:
                continue
            desired = flat_frac * equity
            if r["depth_capped"] and r["cap_shares"] is not None:
                desired = min(desired, r["cap_shares"] * price)
            total_committed = sum(committed.values())
            bucket_committed = committed_by_bucket.get(bucket, 0.0)
            room_agg = agg_cap_pct * equity - total_committed
            room_cat = cat_cap_pct * equity - bucket_committed
            stake = min(desired, room_agg, room_cat, cash)
            if stake <= 1e-6:
                n_skip_capital += 1
                continue
            cash -= stake
            committed[id(r)] = stake
            committed_by_bucket[bucket] = committed_by_bucket.get(bucket, 0.0) + stake
            r["_stake"] = stake
            r["_b"] = b
            r["_L"] = L
            n_taken += 1
            if track_trades:
                r["_entry_equity"] = equity
        else:
            key = id(r)
            if key not in committed:
                equity_series.append((t, cash + sum(committed.values())))
                continue
            bucket = r["report_bucket"]
            stake = committed.pop(key)
            committed_by_bucket[bucket] -= stake
            if r["won"]:
                pnl = stake * r["_b"]
                n_wins_taken += 1
            else:
                pnl = -stake * r["_L"]
                n_flips_taken += 1
            cash += stake + pnl
            if track_trades:
                trade_records.append({
                    "t": r["resolution_time"][:10], "bucket": bucket, "stake": round(stake, 2),
                    "pnl": round(pnl, 2), "won": r["won"], "question": r["question"],
                })
        equity_series.append((t, cash + sum(committed.values())))

    final_equity = cash + sum(committed.values())
    if not equity_series:
        return None

    start_day = equity_series[0][0].date()
    end_day = equity_series[-1][0].date()
    by_day = {}
    for t, eq in equity_series:
        by_day[t.date()] = eq
    daily = []
    d = start_day
    last_eq = START_BANKROLL
    while d <= end_day:
        if d in by_day:
            last_eq = by_day[d]
        daily.append((d, last_eq))
        d += timedelta(days=1)

    span_days = (end_day - start_day).days
    cagr = (final_equity / START_BANKROLL) ** (365.0 / span_days) - 1 if span_days > 0 else float("nan")

    peak = -float("inf")
    max_dd = 0.0
    for _, eq in daily:
        peak = max(peak, eq)
        dd = (peak - eq) / peak if peak > 0 else 0
        max_dd = max(max_dd, dd)

    rets = []
    for i in range(1, len(daily)):
        e0, e1 = daily[i - 1][1], daily[i][1]
        if e0 > 0:
            rets.append(e1 / e0 - 1)
    import math
    mean_r = sum(rets) / len(rets) if rets else 0
    var_r = sum((x - mean_r) ** 2 for x in rets) / len(rets) if rets else 0
    std_r = math.sqrt(var_r)
    sharpe = (mean_r / std_r * math.sqrt(365)) if std_r > 0 else float("nan")

    return {
        "flat_frac": flat_frac,
        "final_equity": round(final_equity, 2),
        "total_return_pct": round((final_equity / START_BANKROLL - 1) * 100, 2),
        "cagr_pct": round(cagr * 100, 2),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "sharpe": round(sharpe, 2) if not math.isnan(sharpe) else None,
        "n_taken": n_taken, "n_skip_capital": n_skip_capital,
        "n_wins_taken": n_wins_taken, "n_flips_taken": n_flips_taken,
        "flip_rate_pct": round(n_flips_taken / n_taken * 100, 4) if n_taken else None,
        "daily_series": [(d.isoformat(), round(eq, 2)) for d, eq in daily],
        "span_days": span_days,
        "trade_records": trade_records if track_trades else None,
    }


def main():
    maker_trades = load("trades_maker.csv")
    res = run_flat_sim([dict(r) for r in maker_trades], FLAT_FRAC, track_trades=True)
    print(f"=== Flat {FLAT_FRAC:.0%}-of-equity sizing, sub-1%-longshot-short population ===")
    print(f"{res['n_taken']} trades taken, {res['n_skip_capital']} skipped for lack of capital "
          f"(50% aggregate / 25% per-category caps)")
    print(f"Flip rate: {res['n_flips_taken']}/{res['n_taken']} = {res['flip_rate_pct']}%")
    print(f"${START_BANKROLL:,.0f} -> ${res['final_equity']:,.2f} ({res['total_return_pct']:+.2f}%)  "
          f"CAGR={res['cagr_pct']:.2f}%  MaxDD={res['max_drawdown_pct']:.2f}%  Sharpe={res['sharpe']}")

    out_path = os.path.join(DATA_DIR, "flat_stake_1pct_results.json")
    with open(out_path, "w") as f:
        json.dump(res, f, indent=2, default=str)
    print(f"saved {out_path}")


if __name__ == "__main__":
    main()
