"""Runs the tennis favorite-longshot-bias backtest: loads cached
tennis-data.co.uk odds, sweeps the favorite-implied-probability threshold,
and reuses the same run_sim / run_flat_sim engines as the football and
Polymarket versions of this strategy. See src/tennis_favorite_bias.py for
the schema translation.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
import tennis_favorite_bias as tfb
from run_kelly_backtest import run_sim, START_BANKROLL
from run_flat_stake_backtest import run_flat_sim

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(REPO, "results", "tennis_favorite_bias")

THRESHOLDS = [0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95]
PRIMARY_THRESHOLD = 0.70
PRIOR_A, PRIOR_B = 5, 15  # same weak Beta(5,15) prior as the football version -- see that
                          # script's comment for why Polymarket's near-certainty prior doesn't apply
SPLIT_DATE_ISO = "2019-01-01"


def raw_diagnostic(matches):
    print("=== Raw diagnostic: favorite win rate vs. quoted price (vig included) ===")
    rows = []
    for thr in THRESHOLDS:
        trades = tfb.build_trades(matches, thr)
        if not trades:
            continue
        n = len(trades)
        wins = sum(1 for t in trades if t["won"])
        win_rate = wins / n
        avg_price = sum(t["entry_price"] for t in trades) / n
        edge_pp = (win_rate - avg_price) * 100
        rows.append({"threshold": thr, "n": n, "win_rate_pct": round(win_rate * 100, 2),
                      "avg_price_pct": round(avg_price * 100, 2), "edge_pp": round(edge_pp, 3)})
        print(f"  thr={thr:.2f}  n={n:6d}  win_rate={win_rate*100:6.2f}%  avg_price={avg_price*100:6.2f}%  edge={edge_pp:+.3f}pp")
    return rows


def bucket_breakdown(trades):
    by_bucket = {}
    for t in trades:
        by_bucket.setdefault(t["report_bucket"], []).append(t)
    rows = []
    for bucket, ts in sorted(by_bucket.items()):
        n = len(ts)
        wins = sum(1 for t in ts if t["won"])
        avg_price = sum(t["entry_price"] for t in ts) / n
        rows.append({"bucket": bucket, "n": n, "win_rate_pct": round(wins / n * 100, 2),
                      "avg_price_pct": round(avg_price * 100, 2), "edge_pp": round((wins / n - avg_price) * 100, 3)})
    return rows


def split_sample_robustness(matches, threshold):
    from datetime import datetime as _dt
    split_dt = _dt.fromisoformat(SPLIT_DATE_ISO)
    early = [m for m in matches if m["match_dt"] < split_dt]
    late = [m for m in matches if m["match_dt"] >= split_dt]
    out = {}
    for label, subset in (("early", early), ("late", late)):
        trades = tfb.build_trades(subset, threshold)
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
    print(f"\n=== Split-sample robustness at {threshold:.0%} (split={SPLIT_DATE_ISO}) ===")
    for label in ("early", "late"):
        r = out[label]
        if r is None:
            print(f"  {label}: insufficient trades")
            continue
        print(f"  {label:<6} {r['date_range'][0]}..{r['date_range'][1]}  n={r['n']:6d}  edge={r['edge_pp']:+.3f}pp  "
              f"Kelly CAGR={r['kelly_cagr_pct']:>7.2f}% Sharpe={r['kelly_sharpe']}  Flat CAGR={r['flat_cagr_pct']:>7.2f}% Sharpe={r['flat_sharpe']}")
    return out


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    matches = tfb.load_matches()
    print(f"loaded {len(matches)} matches (ATP 2002-2025, WTA 2007-2025)\n")

    diag_rows = raw_diagnostic(matches)

    print(f"\n=== Threshold sweep: quarter-Kelly (frac=0.25) vs flat 1%-of-equity ===")
    sweep = {}
    for thr in THRESHOLDS:
        trades = tfb.build_trades(matches, thr)
        if len(trades) < 20:
            continue
        kelly = run_sim([dict(t) for t in trades], fraction=0.25, prior_a=PRIOR_A, prior_b=PRIOR_B)
        flat = run_flat_sim([dict(t) for t in trades], flat_frac=0.01)
        sweep[str(thr)] = {"n_trades": len(trades), "kelly": kelly, "flat": flat}
        print(f"  thr={thr:.2f}  n={len(trades):6d}  "
              f"Kelly: final=${kelly['final_equity']:>12,.2f} CAGR={kelly['cagr_pct']:>7.2f}% Sharpe={kelly['sharpe']}  |  "
              f"Flat 1%: final=${flat['final_equity']:>12,.2f} CAGR={flat['cagr_pct']:>7.2f}% Sharpe={flat['sharpe']}")

    print(f"\n=== Primary case: {PRIMARY_THRESHOLD:.0%} threshold ===")
    primary_trades = tfb.build_trades(matches, PRIMARY_THRESHOLD)
    primary_kelly = run_sim([dict(t) for t in primary_trades], fraction=0.25, prior_a=PRIOR_A, prior_b=PRIOR_B, track_trades=True)
    primary_flat = run_flat_sim([dict(t) for t in primary_trades], flat_frac=0.01, track_trades=True)
    print(f"n={len(primary_trades)}  Kelly: ${START_BANKROLL:,.0f} -> ${primary_kelly['final_equity']:,.2f} "
          f"({primary_kelly['total_return_pct']:+.2f}%)  CAGR={primary_kelly['cagr_pct']:.2f}%  MaxDD={primary_kelly['max_drawdown_pct']:.2f}%  Sharpe={primary_kelly['sharpe']}")
    print(f"n={len(primary_trades)}  Flat 1%: ${START_BANKROLL:,.0f} -> ${primary_flat['final_equity']:,.2f} "
          f"({primary_flat['total_return_pct']:+.2f}%)  CAGR={primary_flat['cagr_pct']:.2f}%  MaxDD={primary_flat['max_drawdown_pct']:.2f}%  Sharpe={primary_flat['sharpe']}")

    bucket_rows = bucket_breakdown(primary_trades)
    print("\nper tour/surface breakdown at 70% threshold:")
    for r in bucket_rows:
        print(f"  {r['bucket']:<12} n={r['n']:6d}  win_rate={r['win_rate_pct']:6.2f}%  avg_price={r['avg_price_pct']:6.2f}%  edge={r['edge_pp']:+.3f}pp")

    split_robustness = split_sample_robustness(matches, PRIMARY_THRESHOLD)

    summary = {
        "n_matches_total": len(matches),
        "prior_a": PRIOR_A, "prior_b": PRIOR_B,
        "raw_diagnostic": diag_rows,
        "threshold_sweep": {
            k: {
                "n_trades": v["n_trades"],
                "kelly": {kk: v["kelly"][kk] for kk in ["final_equity", "total_return_pct", "cagr_pct", "max_drawdown_pct", "sharpe", "n_taken", "n_wins_taken", "n_flips_taken"]},
                "flat": {kk: v["flat"][kk] for kk in ["final_equity", "total_return_pct", "cagr_pct", "max_drawdown_pct", "sharpe", "n_taken", "n_wins_taken", "n_flips_taken"]},
            } for k, v in sweep.items()
        },
        "primary_threshold": PRIMARY_THRESHOLD,
        "primary_kelly": {k: primary_kelly[k] for k in ["final_equity", "total_return_pct", "cagr_pct", "max_drawdown_pct", "sharpe", "n_taken", "n_skip_noedge", "n_skip_capital", "n_wins_taken", "n_flips_taken"]},
        "primary_flat": {k: primary_flat[k] for k in ["final_equity", "total_return_pct", "cagr_pct", "max_drawdown_pct", "sharpe", "n_taken", "n_skip_capital", "n_wins_taken", "n_flips_taken"]},
        "primary_kelly_equity_curve": primary_kelly["daily_series"],
        "primary_flat_equity_curve": primary_flat["daily_series"],
        "bucket_breakdown": bucket_rows,
        "split_sample_robustness": split_robustness,
        "split_date": SPLIT_DATE_ISO,
    }
    out_path = os.path.join(OUT_DIR, "tennis_favorite_bias_results.json")
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\nsaved {out_path}")


if __name__ == "__main__":
    main()
