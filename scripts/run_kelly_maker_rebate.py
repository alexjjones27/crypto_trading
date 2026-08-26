"""Extends run_kelly_backtest.py with the maker rebate Polymarket actually
pays (confirmed against docs.polymarket.com/programs/maker-rebates):
20% (crypto), 15% (sports), 25% (politics/other/finance/...), 0% (geopolitics)
of the taker fee that would otherwise have been charged to your counterparty.

The rebate is paid on trading activity, funded by the taker-fee pool -- it
is NOT contingent on how the position itself resolves. So it enters the
Kelly edge as a per-trade credit on BOTH branches:

  win:  pnl = stake * b_rebate,      b_rebate = (1-price)/price + rebate_frac
  loss: pnl = -stake * L_rebate,     L_rebate = 1 - rebate_frac

where rebate_frac = REBATE_RATE[category] * FEE_RATE[category] * (1-price)
is the rebate as a fraction of notional (the same units run_kelly_backtest
uses for fee_frac). This is a strict improvement to both branches of the
same walk-forward Kelly formula already built -- not a new model.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_kelly_backtest import load, DATA_DIR, PRIOR_A, PRIOR_B, MAX_POS_PCT, AGG_CAP_PCT, CAT_CAP_PCT, START_BANKROLL
import math
from datetime import timedelta

# Confirmed live against docs.polymarket.com/programs/maker-rebates (2026-08-26)
REBATE_RATE = {"crypto": 0.20, "sports": 0.15, "politics": 0.25, "other": 0.25, "finance": 0.25,
               "tech": 0.25, "mentions": 0.25, "economics": 0.25, "culture": 0.25, "weather": 0.25,
               "geopolitics": 0.0}
FEE_RATE = {"crypto": 0.07, "sports": 0.05, "politics": 0.04, "other": 0.05, "finance": 0.04,
            "tech": 0.04, "mentions": 0.04, "economics": 0.05, "culture": 0.05, "weather": 0.05,
            "geopolitics": 0.0}


def run_sim_rebate(all_trades, fraction, max_pos_pct=MAX_POS_PCT, agg_cap_pct=AGG_CAP_PCT, cat_cap_pct=CAT_CAP_PCT):
    tradeable = [r for r in all_trades if not r["excluded"]]
    events = []
    for r in tradeable:
        resolve_key_t = max(r["resolve_dt"], r["entry_dt"])
        events.append((r["entry_dt"], 0, "entry", r))
        events.append((resolve_key_t, 1, "resolve", r))
    events.sort(key=lambda e: (e[0], e[1]))

    bucket_flips, bucket_n = {}, {}

    def qh(bucket):
        k = bucket_flips.get(bucket, 0)
        n = bucket_n.get(bucket, 0)
        return (PRIOR_A + k) / (PRIOR_A + PRIOR_B + n)

    cash = START_BANKROLL
    committed, committed_by_bucket = {}, {}
    equity_series = []
    n_taken = n_skip_noedge = n_skip_capital = n_flips_taken = n_wins_taken = 0
    total_rebate_collected = 0.0

    for t, order, kind, r in events:
        if kind == "entry":
            bucket = r["report_bucket"]
            category = r["category"]
            price = r["entry_price"]
            rebate_rate = REBATE_RATE.get(category, 0.25)
            fee_rate = FEE_RATE.get(category, 0.05)
            rebate_frac = rebate_rate * fee_rate * (1.0 - price)

            b = (1.0 - price) / price + rebate_frac  # maker fee is already $0; rebate adds on top
            L = 1.0 - rebate_frac
            equity = cash + sum(committed.values())
            if b <= 0:
                n_skip_noedge += 1
                continue
            q = qh(bucket)
            p = 1.0 - q
            f_kelly = (p * b - q * L) / (b * L)
            if f_kelly <= 0:
                n_skip_noedge += 1
                continue
            desired = min(f_kelly * fraction * equity, max_pos_pct * equity)
            if r["depth_capped"] and r["cap_shares"] is not None:
                desired = min(desired, r["cap_shares"] * price)
            room_agg = agg_cap_pct * equity - sum(committed.values())
            room_cat = cat_cap_pct * equity - committed_by_bucket.get(bucket, 0.0)
            stake = min(desired, room_agg, room_cat, cash)
            if stake <= 1e-6:
                n_skip_capital += 1
                continue
            cash -= stake
            committed[id(r)] = stake
            committed_by_bucket[bucket] = committed_by_bucket.get(bucket, 0.0) + stake
            r["_stake"], r["_b"], r["_L"], r["_rebate_frac"] = stake, b, L, rebate_frac
            n_taken += 1
        else:
            bucket = r["report_bucket"]
            bucket_n[bucket] = bucket_n.get(bucket, 0) + 1
            if not r["won"]:
                bucket_flips[bucket] = bucket_flips.get(bucket, 0) + 1
            key = id(r)
            if key not in committed:
                equity_series.append((t, cash + sum(committed.values())))
                continue
            stake = committed.pop(key)
            committed_by_bucket[bucket] -= stake
            rebate_dollars = stake * r["_rebate_frac"]
            total_rebate_collected += rebate_dollars
            if r["won"]:
                pnl = stake * r["_b"]
                n_wins_taken += 1
            else:
                pnl = -stake * r["_L"]
                n_flips_taken += 1
            cash += stake + pnl
        equity_series.append((t, cash + sum(committed.values())))

    final_equity = cash + sum(committed.values())
    if not equity_series:
        return None
    start_day, end_day = equity_series[0][0].date(), equity_series[-1][0].date()
    by_day = {}
    for t, eq in equity_series:
        by_day[t.date()] = eq
    daily, d, last_eq = [], start_day, START_BANKROLL
    while d <= end_day:
        if d in by_day:
            last_eq = by_day[d]
        daily.append((d, last_eq))
        d += timedelta(days=1)
    span_days = (end_day - start_day).days
    cagr = (final_equity / START_BANKROLL) ** (365.0 / span_days) - 1 if span_days > 0 else float("nan")
    peak, max_dd = -math.inf, 0.0
    for _, eq in daily:
        peak = max(peak, eq)
        max_dd = max(max_dd, (peak - eq) / peak if peak > 0 else 0)
    rets = [daily[i][1] / daily[i - 1][1] - 1 for i in range(1, len(daily)) if daily[i - 1][1] > 0]
    mean_r = sum(rets) / len(rets) if rets else 0
    std_r = math.sqrt(sum((x - mean_r) ** 2 for x in rets) / len(rets)) if rets else 0
    sharpe = (mean_r / std_r * math.sqrt(365)) if std_r > 0 else float("nan")

    return {
        "fraction": fraction, "final_equity": round(final_equity, 2),
        "total_return_pct": round((final_equity / START_BANKROLL - 1) * 100, 2),
        "cagr_pct": round(cagr * 100, 2), "max_drawdown_pct": round(max_dd * 100, 2),
        "sharpe": round(sharpe, 2) if not math.isnan(sharpe) else None,
        "n_taken": n_taken, "n_skip_noedge": n_skip_noedge, "n_skip_capital": n_skip_capital,
        "n_wins_taken": n_wins_taken, "n_flips_taken": n_flips_taken,
        "total_rebate_collected": round(total_rebate_collected, 2),
        "span_days": span_days,
    }


def main():
    maker_trades = load("trades_maker.csv")
    print("=== Without rebate (Kelly, Capped baseline) vs. With rebate ===")
    from run_kelly_backtest import run_sim
    without = run_sim([dict(r) for r in maker_trades], 0.25)
    with_rebate = run_sim_rebate([dict(r) for r in maker_trades], 0.25)
    for label, res in [("without rebate", without), ("with rebate", with_rebate)]:
        print(f"{label:<16} final=${res['final_equity']:>10,.0f}  CAGR={res['cagr_pct']:>6.1f}%  "
              f"MaxDD={res['max_drawdown_pct']:>5.1f}%  Sharpe={res['sharpe']}  taken={res['n_taken']}  "
              f"flips={res['n_flips_taken']}" +
              (f"  rebate_collected=${res['total_rebate_collected']:,.0f}" if "total_rebate_collected" in res else ""))

    print("\n=== Fraction sweep, with rebate ===")
    results = {}
    for frac in [1.0, 0.5, 0.25, 0.125, 0.0625]:
        res = run_sim_rebate([dict(r) for r in maker_trades], frac)
        results[str(frac)] = res
        print(f"frac={frac:<8} final=${res['final_equity']:>10,.0f}  CAGR={res['cagr_pct']:>6.1f}%  "
              f"MaxDD={res['max_drawdown_pct']:>5.1f}%  Sharpe={res['sharpe']}  "
              f"rebate=${res['total_rebate_collected']:,.0f}")

    out = {"without_rebate": without, "with_rebate": with_rebate, "fraction_sweep": results}
    out_path = os.path.join(DATA_DIR, "kelly_maker_rebate.json")
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)
    print("\nsaved", out_path)


if __name__ == "__main__":
    main()
