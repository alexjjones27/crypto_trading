"""Runs the football favorite-longshot-bias backtest: loads cached
football-data.co.uk closing lines, sweeps the favorite-implied-probability
threshold, and re-uses the exact Kelly (run_kelly_backtest.run_sim) and flat
(run_flat_stake_backtest.run_flat_sim) engines already validated on the
Polymarket Final-1% project. See src/football_favorite_bias.py for the
schema translation this relies on.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
import football_favorite_bias as ffb
from run_kelly_backtest import run_sim, START_BANKROLL
from run_flat_stake_backtest import run_flat_sim

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(REPO, "results", "football_favorite_bias")

THRESHOLDS = [0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95]
PRIMARY_THRESHOLD = 0.70

# Weak-informative Beta prior on the per-league "flip" (loss) rate, centered
# near the pooled base rate at the primary 70% threshold (~21% loss rate --
# see the raw-vs-devigged diagnostic printed below) with modest strength
# (n=20 pseudo-observations) so real per-league data dominates quickly.
# Polymarket's PRIOR_A=1, PRIOR_B=300 assumed a near-certain (<1%) flip rate,
# appropriate for 99%+ markets but wildly wrong at a 70% threshold -- reusing
# it here would grossly oversize the first trades in every league before the
# walk-forward belief caught up.
PRIOR_A, PRIOR_B = 5, 15


def raw_vs_devigged_diagnostic(matches):
    """Sanity check ported from the Polymarket project's habit of validating
    the strategy's core assumption before trusting the backtest: does the
    realized favorite win rate exceed the VIG-INCLUDED closing price (a
    trader's actual break-even bar), at each threshold? And separately, what
    is the average overround (bookmaker margin) in this population?"""
    print("=== Raw diagnostic: favorite win rate vs. closing implied price (vig included) ===")
    overrounds = []
    for m in matches:
        overrounds.append(1.0 / m["odds_h"] + 1.0 / m["odds_d"] + 1.0 / m["odds_a"] - 1.0)
    print(f"mean overround (bookmaker margin) across {len(matches)} matches: {sum(overrounds)/len(overrounds)*100:.2f}%")
    rows = []
    for thr in THRESHOLDS:
        trades = ffb.build_trades(matches, thr)
        if not trades:
            continue
        n = len(trades)
        wins = sum(1 for t in trades if t["won"])
        win_rate = wins / n
        avg_price = sum(t["entry_price"] for t in trades) / n
        edge_pp = (win_rate - avg_price) * 100
        rows.append({"threshold": thr, "n": n, "win_rate_pct": round(win_rate * 100, 2),
                      "avg_closing_price_pct": round(avg_price * 100, 2), "edge_pp": round(edge_pp, 3)})
        print(f"  thr={thr:.2f}  n={n:6d}  win_rate={win_rate*100:6.2f}%  avg_price={avg_price*100:6.2f}%  "
              f"edge={edge_pp:+.3f}pp {'(profitable before staking)' if edge_pp > 0 else ''}")
    return rows


def league_breakdown(trades):
    by_league = {}
    for t in trades:
        by_league.setdefault(t["league"], []).append(t)
    rows = []
    for league, ts in sorted(by_league.items()):
        n = len(ts)
        wins = sum(1 for t in ts if t["won"])
        avg_price = sum(t["entry_price"] for t in ts) / n
        rows.append({
            "league": league, "league_name": ffb.LEAGUE_NAMES.get(league, league), "n": n,
            "win_rate_pct": round(wins / n * 100, 2), "avg_closing_price_pct": round(avg_price * 100, 2),
            "edge_pp": round((wins / n - avg_price) * 100, 3),
        })
    return rows


SPLIT_DATE_ISO = "2019-07-01"


def split_sample_robustness(matches, threshold):
    """Independence check: does the per-league edge at the primary threshold
    hold up if the sample is split into two disjoint time periods, each with
    its OWN cold-start walk-forward belief (no information carried across
    the split)? A real, structural mispricing should show up in both
    halves; an edge that only appears in the pooled backtest is more likely
    an artifact of one lucky sub-period or the walk-forward model overfitting
    within-sample. This is the same spirit check as this repo's
    scripts/leakage_check.py for the Polymarket project, adapted to a
    train/test time split rather than a lookahead check."""
    from datetime import datetime as _dt
    split_dt = _dt.fromisoformat(SPLIT_DATE_ISO)
    early = [m for m in matches if m["kickoff_dt"] < split_dt]
    late = [m for m in matches if m["kickoff_dt"] >= split_dt]
    out = {}
    for label, subset in (("early", early), ("late", late)):
        trades = ffb.build_trades(subset, threshold)
        if len(trades) < 20:
            out[label] = None
            continue
        n = len(trades)
        wins = sum(1 for t in trades if t["won"])
        avg_price = sum(t["entry_price"] for t in trades) / n
        kelly = run_sim([dict(t) for t in trades], fraction=0.25, prior_a=PRIOR_A, prior_b=PRIOR_B)
        flat = run_flat_sim([dict(t) for t in trades], flat_frac=0.01)
        out[label] = {
            "date_range": [trades[0]["entry_time"][:10], trades[-1]["entry_time"][:10]],
            "n": n, "win_rate_pct": round(wins / n * 100, 2), "avg_price_pct": round(avg_price * 100, 2),
            "edge_pp": round((wins / n - avg_price) * 100, 3),
            "kelly_cagr_pct": kelly["cagr_pct"] if kelly else None, "kelly_sharpe": kelly["sharpe"] if kelly else None,
            "flat_cagr_pct": flat["cagr_pct"] if flat else None, "flat_sharpe": flat["sharpe"] if flat else None,
        }
    print(f"\n=== Split-sample robustness at {threshold:.0%} threshold (split={SPLIT_DATE_ISO}, independent cold-start belief each half) ===")
    for label in ("early", "late"):
        r = out[label]
        if r is None:
            print(f"  {label}: insufficient trades")
            continue
        print(f"  {label:<6} {r['date_range'][0]}..{r['date_range'][1]}  n={r['n']:5d}  edge={r['edge_pp']:+.3f}pp  "
              f"Kelly CAGR={r['kelly_cagr_pct']:>7.2f}% Sharpe={r['kelly_sharpe']}  Flat CAGR={r['flat_cagr_pct']:>7.2f}% Sharpe={r['flat_sharpe']}")
    return out


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    matches = ffb.load_matches()
    print(f"loaded {len(matches)} matches with usable closing odds across {len(set(m['league'] for m in matches))} leagues\n")

    diagnostic_rows = raw_vs_devigged_diagnostic(matches)

    print(f"\n=== Threshold sweep: quarter-Kelly (frac=0.25) vs flat 1%-of-equity ===")
    sweep = {}
    for thr in THRESHOLDS:
        trades = ffb.build_trades(matches, thr)
        if len(trades) < 20:
            continue
        kelly = run_sim([dict(t) for t in trades], fraction=0.25, prior_a=PRIOR_A, prior_b=PRIOR_B)
        flat = run_flat_sim([dict(t) for t in trades], flat_frac=0.01)
        sweep[str(thr)] = {"n_trades": len(trades), "kelly": kelly, "flat": flat}
        k_final = kelly["final_equity"] if kelly else None
        f_final = flat["final_equity"] if flat else None
        print(f"  thr={thr:.2f}  n={len(trades):6d}  "
              f"Kelly: final=${k_final:>12,.2f} CAGR={kelly['cagr_pct'] if kelly else float('nan'):>7.2f}% Sharpe={kelly['sharpe'] if kelly else None}  |  "
              f"Flat 1%: final=${f_final:>12,.2f} CAGR={flat['cagr_pct'] if flat else float('nan'):>7.2f}% Sharpe={flat['sharpe'] if flat else None}")

    print(f"\n=== Primary case: {PRIMARY_THRESHOLD:.0%} threshold, trade-level detail + per-league breakdown ===")
    primary_trades = ffb.build_trades(matches, PRIMARY_THRESHOLD)
    primary_kelly = run_sim([dict(t) for t in primary_trades], fraction=0.25, prior_a=PRIOR_A, prior_b=PRIOR_B, track_trades=True)
    primary_flat = run_flat_sim([dict(t) for t in primary_trades], flat_frac=0.01, track_trades=True)
    print(f"n={len(primary_trades)}  Kelly: ${START_BANKROLL:,.0f} -> ${primary_kelly['final_equity']:,.2f} "
          f"({primary_kelly['total_return_pct']:+.2f}%)  CAGR={primary_kelly['cagr_pct']:.2f}%  "
          f"MaxDD={primary_kelly['max_drawdown_pct']:.2f}%  Sharpe={primary_kelly['sharpe']}")
    print(f"n={len(primary_trades)}  Flat 1%: ${START_BANKROLL:,.0f} -> ${primary_flat['final_equity']:,.2f} "
          f"({primary_flat['total_return_pct']:+.2f}%)  CAGR={primary_flat['cagr_pct']:.2f}%  "
          f"MaxDD={primary_flat['max_drawdown_pct']:.2f}%  Sharpe={primary_flat['sharpe']}")

    league_rows = league_breakdown(primary_trades)
    print("\nper-league breakdown at 70% threshold:")
    for r in league_rows:
        print(f"  {r['league']:<5} {r['league_name']:<28} n={r['n']:5d}  win_rate={r['win_rate_pct']:6.2f}%  "
              f"avg_price={r['avg_closing_price_pct']:6.2f}%  edge={r['edge_pp']:+.3f}pp")

    split_robustness = split_sample_robustness(matches, PRIMARY_THRESHOLD)

    summary = {
        "n_matches_total": len(matches),
        "prior_a": PRIOR_A, "prior_b": PRIOR_B,
        "raw_vs_devigged_diagnostic": diagnostic_rows,
        "threshold_sweep": {
            k: {
                "n_trades": v["n_trades"],
                "kelly": {kk: v["kelly"][kk] for kk in ["final_equity", "total_return_pct", "cagr_pct", "max_drawdown_pct", "sharpe", "n_taken", "n_wins_taken", "n_flips_taken"]} if v["kelly"] else None,
                "flat": {kk: v["flat"][kk] for kk in ["final_equity", "total_return_pct", "cagr_pct", "max_drawdown_pct", "sharpe", "n_taken", "n_wins_taken", "n_flips_taken"]} if v["flat"] else None,
            } for k, v in sweep.items()
        },
        "primary_threshold": PRIMARY_THRESHOLD,
        "primary_kelly": {k: primary_kelly[k] for k in ["final_equity", "total_return_pct", "cagr_pct", "max_drawdown_pct", "sharpe", "n_taken", "n_skip_noedge", "n_skip_capital", "n_wins_taken", "n_flips_taken"]},
        "primary_flat": {k: primary_flat[k] for k in ["final_equity", "total_return_pct", "cagr_pct", "max_drawdown_pct", "sharpe", "n_taken", "n_skip_capital", "n_wins_taken", "n_flips_taken"]},
        "primary_kelly_equity_curve": primary_kelly["daily_series"],
        "primary_flat_equity_curve": primary_flat["daily_series"],
        "league_breakdown": league_rows,
        "split_sample_robustness": split_robustness,
        "split_date": SPLIT_DATE_ISO,
    }
    out_path = os.path.join(OUT_DIR, "football_favorite_bias_results.json")
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\nsaved {out_path}")


if __name__ == "__main__":
    main()
