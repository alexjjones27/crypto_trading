"""Buying the longshot itself (the mirror image of shorting it).

Every trade in trades_maker.csv is "buy the ~99%+ token." In a binary
market the two outcome tokens are complementary, so the trade this script
evaluates -- buying the OTHER (sub-1%) token instead -- is implicit in the
same data: it wins exactly when the original trade lost (a "flip"), and
loses exactly when the original trade won. No new price-history fetch is
needed; only the complement's entry price is approximated as
(1 - original_entry_price), since the exact contemporaneous complement
price isn't stored (only the winning-side crossing was recorded during the
original scan). This is a reasonable approximation given original entries
already sit at >=0.99 (so the complement is within a cent or two of
1-price), documented here rather than silently assumed.

This is the direct empirical test of favorite-longshot bias from the other
side: does buying cheap, likely-to-lose tickets ever pay off in this
population? Given only 3 flips were observed across the entire dataset,
the expected answer is a clearly negative-EV strategy -- this script
proves that with real numbers rather than asserting it.
"""
import json
import math
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_kelly_backtest import load, DATA_DIR, START_BANKROLL

FLAT_FRAC = 0.01
FIXED_NOTIONAL = 100.0


def mirror_trades(all_trades):
    """One row per original trade -> the complement ("buy the longshot")
    trade: entry price ~ 1 - original price, wins iff the original flipped."""
    out = []
    for r in all_trades:
        if r["excluded"]:
            continue
        longshot_price = max(1e-4, 1.0 - r["entry_price"])
        won = not r["won"]  # longshot wins exactly when the original flipped
        out.append({
            "entry_dt": r["entry_dt"], "resolve_dt": r["resolve_dt"],
            "entry_price": longshot_price, "fee_frac": r["fee_frac"],
            "won": won, "question": r["question"], "report_bucket": r["report_bucket"],
        })
    return out


def fixed_notional_summary(trades, notional=FIXED_NOTIONAL):
    total_cost = 0.0
    total_payout = 0.0
    total_fee = 0.0
    n_wins = 0
    win_rows = []
    for r in trades:
        price = r["entry_price"]
        shares = notional / price
        fee = shares * r["fee_frac"] * price * (1 - price)
        cost = notional + fee
        payout = shares * 1.0 if r["won"] else 0.0
        total_cost += cost
        total_payout += payout
        total_fee += fee
        if r["won"]:
            n_wins += 1
            win_rows.append({"date": r["resolve_dt"].isoformat()[:10], "question": r["question"],
                              "entry_price": round(price, 4), "payout": round(payout, 2)})
    n = len(trades)
    return {
        "n_trades": n, "n_wins": n_wins, "win_rate_pct": round(n_wins / n * 100, 4) if n else None,
        "fixed_notional_per_trade": notional,
        "total_staked": round(sum(notional for _ in trades), 2),
        "total_cost_incl_fees": round(total_cost, 2),
        "total_payout": round(total_payout, 2),
        "net_pnl": round(total_payout - total_cost, 2),
        "roi_pct": round((total_payout - total_cost) / total_cost * 100, 3) if total_cost else None,
        "breakeven_win_rate_pct": round(
            sum(r["entry_price"] for r in trades) / n * 100, 3) if n else None,  # avg price ~ implied breakeven rate
        "winning_trades": win_rows,
    }


def flat_frac_sim(trades, flat_frac=FLAT_FRAC):
    events = []
    for r in trades:
        resolve_key_t = max(r["resolve_dt"], r["entry_dt"])
        events.append((r["entry_dt"], 0, "entry", r))
        events.append((resolve_key_t, 1, "resolve", r))
    events.sort(key=lambda e: (e[0], e[1]))

    cash = START_BANKROLL
    committed = {}
    equity_series = []
    n_taken = 0
    for t, order, kind, r in events:
        if kind == "entry":
            equity = cash + sum(v[0] for v in committed.values())
            price = r["entry_price"]
            stake = min(flat_frac * equity, cash)
            if stake <= 1e-6:
                continue
            cash -= stake
            shares = stake / price
            committed[id(r)] = (stake, shares, r)
            n_taken += 1
        else:
            key = id(r)
            if key not in committed:
                equity_series.append((t, cash + sum(v[0] for v in committed.values())))
                continue
            stake, shares, _ = committed.pop(key)
            fee = shares * r["fee_frac"] * r["entry_price"] * (1 - r["entry_price"])
            payout = (shares * 1.0 if r["won"] else 0.0) - fee
            cash += payout
        equity_series.append((t, cash + sum(v[0] for v in committed.values())))

    final_equity = cash + sum(v[0] for v in committed.values())
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
    peak = -math.inf
    max_dd = 0.0
    for _, eq in daily:
        peak = max(peak, eq)
        dd = (peak - eq) / peak if peak > 0 else 0
        max_dd = max(max_dd, dd)

    return {
        "flat_frac": flat_frac, "n_taken": n_taken,
        "final_equity": round(final_equity, 2),
        "total_return_pct": round((final_equity / START_BANKROLL - 1) * 100, 2),
        "cagr_pct": round(cagr * 100, 2),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "daily_series": [(d.isoformat(), round(eq, 2)) for d, eq in daily],
        "span_days": span_days,
    }


def main():
    maker_trades = load("trades_maker.csv")
    longshots = mirror_trades(maker_trades)
    print(f"{len(longshots)} mirror (buy-the-longshot) trades derived from trades_maker.csv\n")

    fixed = fixed_notional_summary(longshots)
    print(f"=== Fixed ${FIXED_NOTIONAL:.0f}-notional-per-trade summary ===")
    print(f"Trades: {fixed['n_trades']}   Wins: {fixed['n_wins']} ({fixed['win_rate_pct']}%)")
    print(f"Total staked: ${fixed['total_staked']:,.2f}   Total cost (incl. fees): ${fixed['total_cost_incl_fees']:,.2f}")
    print(f"Total payout: ${fixed['total_payout']:,.2f}")
    print(f"Net P&L: ${fixed['net_pnl']:,.2f}  (ROI: {fixed['roi_pct']}%)")
    print(f"Average entry price (~ breakeven win rate needed): {fixed['breakeven_win_rate_pct']}%   "
          f"vs. realized win rate: {fixed['win_rate_pct']}%")
    print("\nWinning trades (the only ones that paid off):")
    for w in fixed["winning_trades"]:
        print(f"  {w['date']}  {w['question'][:60]!r}  entry=${w['entry_price']}  payout=${w['payout']:,.2f}")

    flat = flat_frac_sim(longshots)
    print(f"\n=== Flat {FLAT_FRAC:.0%}-of-equity compounding sizing ===")
    print(f"{flat['n_taken']} trades taken")
    print(f"${START_BANKROLL:,.0f} -> ${flat['final_equity']:,.2f} ({flat['total_return_pct']:+.2f}%)  "
          f"CAGR={flat['cagr_pct']:.2f}%  MaxDD={flat['max_drawdown_pct']:.2f}%")

    out = {"fixed_notional": fixed, "flat_frac_sim": flat}
    out_path = os.path.join(DATA_DIR, "longshot_buy_results.json")
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\nsaved {out_path}")


if __name__ == "__main__":
    main()
