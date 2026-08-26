"""Run the recommended Kelly-sized $10,000-bankroll configuration (quarter-
Kelly, 3% max position, exact-score/weather exclusion) against each of the
threshold-swept trade files from run_threshold_sweep.py, to see how the
entry probability itself -- not just position sizing -- trades off return
against risk. Requires trades_maker_thr*.csv to already exist.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_kelly_backtest import load, run_sim, DATA_DIR

THRESHOLD_FILES = [
    ("0.980", "trades_maker_thr098.csv"),
    ("0.985", "trades_maker_thr0985.csv"),
    ("0.990", "trades_maker_thr099.csv"),
    ("0.990 (original sample)", "trades_maker.csv"),
    ("0.995", "trades_maker_thr0995.csv"),
    ("0.999", "trades_maker_thr0999.csv"),
]


def main():
    results = []
    for label, fn in THRESHOLD_FILES:
        path = os.path.join(DATA_DIR, fn)
        if not os.path.exists(path):
            print(f"skip {label}: {fn} not found")
            continue
        trades = load(fn)
        n_total = len(trades)
        n_excluded = sum(1 for r in trades if r["excluded"])
        res = run_sim([dict(r) for r in trades], fraction=0.25)
        row = {
            "threshold": label,
            "n_total_trades": n_total,
            "n_excluded": n_excluded,
            "n_taken": res["n_taken"],
            "n_flips_taken": res["n_flips_taken"],
            "final_equity": res["final_equity"],
            "total_return_pct": res["total_return_pct"],
            "cagr_pct": res["cagr_pct"],
            "max_drawdown_pct": res["max_drawdown_pct"],
            "sharpe": res["sharpe"],
        }
        results.append(row)
        print(
            f"thr={label:<24} total={n_total:<5} excl={n_excluded:<4} taken={res['n_taken']:<5} "
            f"flips={res['n_flips_taken']:<3} final=${res['final_equity']:>10,.0f} "
            f"CAGR={res['cagr_pct']:>6.1f}%  MaxDD={res['max_drawdown_pct']:>5.1f}%  Sharpe={res['sharpe']}"
        )

    out_path = os.path.join(DATA_DIR, "kelly_threshold_sweep.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print("saved", out_path)


if __name__ == "__main__":
    main()
