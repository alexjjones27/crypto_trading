"""Summarizes flip-rate and flat-1% P&L across the full threshold sweep
(0.70 -> 0.999), using the unbiased stratified-sample trade files already
built by run_threshold_sweep.py. Answers: does the favorite-longshot bias
hold at less extreme prices, not just the sub-1%/99%+ tail?
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from run_kelly_backtest import load, DATA_DIR
from run_flat_stake_backtest import run_flat_sim
import polymarket_final_pct as pmf

THRESHOLDS = ["07", "08", "09", "095", "097", "098", "0985", "099", "0995", "0999"]
THRESHOLD_VALUES = [0.70, 0.80, 0.90, 0.95, 0.97, 0.98, 0.985, 0.99, 0.995, 0.999]


def main():
    rows = []
    for thr_str, thr_val in zip(THRESHOLDS, THRESHOLD_VALUES):
        fn = f"trades_maker_thr{thr_str}.csv"
        path = os.path.join(DATA_DIR, fn)
        if not os.path.exists(path):
            print(f"  (missing {fn}, skipping)")
            continue
        trades = load(fn)
        tradeable = [r for r in trades if not r["excluded"]]
        n = len(tradeable)
        n_flips = sum(1 for r in tradeable if not r["won"])
        flip_rate = n_flips / n if n else float("nan")
        wilson_lo, wilson_hi = pmf.wilson_interval(n_flips, n)
        cp_lo, cp_hi = pmf.clopper_pearson_interval(n_flips, n)

        flat = run_flat_sim([dict(r) for r in trades], flat_frac=0.01)

        row = {
            "threshold": thr_val, "n_trades": n, "n_flips": n_flips,
            "flip_rate_pct": round(flip_rate * 100, 4),
            "wilson_95ci_pct": [round(wilson_lo * 100, 4), round(wilson_hi * 100, 4)],
            "clopper_pearson_95ci_pct": [round(cp_lo * 100, 4), round(cp_hi * 100, 4)],
            "flat1pct_final_equity": flat["final_equity"],
            "flat1pct_total_return_pct": flat["total_return_pct"],
            "flat1pct_cagr_pct": flat["cagr_pct"],
            "flat1pct_max_drawdown_pct": flat["max_drawdown_pct"],
            "flat1pct_sharpe": flat["sharpe"],
        }
        rows.append(row)
        print(f"thr={thr_val:<6} n={n:<5} flips={n_flips:<4} flip_rate={row['flip_rate_pct']:>7.3f}%  "
              f"wilson95=[{row['wilson_95ci_pct'][0]:.3f}, {row['wilson_95ci_pct'][1]:.3f}]  "
              f"final=${flat['final_equity']:>10,.2f}  CAGR={flat['cagr_pct']:>6.2f}%  "
              f"MaxDD={flat['max_drawdown_pct']:>5.2f}%  Sharpe={flat['sharpe']}")

    out_path = os.path.join(DATA_DIR, "threshold_sensitivity_summary.json")
    with open(out_path, "w") as f:
        json.dump(rows, f, indent=2)
    print(f"\nsaved {out_path}")


if __name__ == "__main__":
    main()
