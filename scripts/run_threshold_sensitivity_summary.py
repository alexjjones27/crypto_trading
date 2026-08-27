"""Summarizes flip-rate, flat-1%, and quarter-Kelly P&L across the full
threshold sweep (0.70 -> 0.999), using the unbiased stratified-sample trade
files built by run_threshold_sweep.py. Answers: does the favorite-longshot
bias hold at less extreme prices, not just the sub-1%/99%+ tail, and does
proper walk-forward Kelly sizing change the picture versus flat sizing?

Calibration caveat, worth stating up front rather than burying: the Kelly
walk-forward flip-rate belief uses the SAME Beta(1, 300) prior at every
threshold, unchanged from where it was calibrated (the ~99%+ population,
where true flip rates run under 0.2%). At looser thresholds the true flip
rate is far higher (12%+ at 70%), so that prior starts out badly
miscalibrated for this population -- it initially underestimates risk and
only corrects as real observations accumulate within each category over
time. This isn't a new prior tuned for this threshold; it's the existing
one, run as-is, so the 70% Kelly numbers below should be read knowing the
sizing was too aggressive early in the backtest before the belief caught
up to the true, much higher, flip rate at this looser threshold.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from run_kelly_backtest import load, DATA_DIR, run_sim
from run_flat_stake_backtest import run_flat_sim
import polymarket_final_pct as pmf

KELLY_FRACTION = 0.25  # quarter-Kelly, the fraction used as "recommended" throughout this project

THRESHOLDS = ["07", "08", "09", "095", "097", "098", "0985", "099", "0995", "0999"]
THRESHOLD_VALUES = [0.70, 0.80, 0.90, 0.95, 0.97, 0.98, 0.985, 0.99, 0.995, 0.999]


def main(suffix=""):
    rows = []
    for thr_str, thr_val in zip(THRESHOLDS, THRESHOLD_VALUES):
        fn = f"trades_maker_thr{thr_str}{suffix}.csv"
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
        kelly = run_sim([dict(r) for r in trades], fraction=KELLY_FRACTION)

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
            "kelly_final_equity": kelly["final_equity"],
            "kelly_total_return_pct": kelly["total_return_pct"],
            "kelly_cagr_pct": kelly["cagr_pct"],
            "kelly_max_drawdown_pct": kelly["max_drawdown_pct"],
            "kelly_sharpe": kelly["sharpe"],
            "kelly_n_taken": kelly["n_taken"],
            "kelly_n_skip_noedge": kelly["n_skip_noedge"],
            "kelly_n_skip_capital": kelly["n_skip_capital"],
            "kelly_n_flips_taken": kelly["n_flips_taken"],
        }
        rows.append(row)
        print(f"thr={thr_val:<6} n={n:<5} flips={n_flips:<4} flip_rate={row['flip_rate_pct']:>7.3f}%  "
              f"flat: final=${flat['final_equity']:>10,.2f} CAGR={flat['cagr_pct']:>6.2f}% "
              f"MaxDD={flat['max_drawdown_pct']:>5.2f}% Sharpe={flat['sharpe']}  |  "
              f"kelly({KELLY_FRACTION}): final=${kelly['final_equity']:>10,.2f} CAGR={kelly['cagr_pct']:>6.2f}% "
              f"MaxDD={kelly['max_drawdown_pct']:>5.2f}% Sharpe={kelly['sharpe']} "
              f"taken={kelly['n_taken']} skip_edge={kelly['n_skip_noedge']} skip_cap={kelly['n_skip_capital']}")

    out_path = os.path.join(DATA_DIR, f"threshold_sensitivity_summary{suffix}.json")
    with open(out_path, "w") as f:
        json.dump(rows, f, indent=2)
    print(f"\nsaved {out_path}")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--suffix", type=str, default="")
    args = p.parse_args()
    main(args.suffix)
