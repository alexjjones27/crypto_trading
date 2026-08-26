"""Sweeps the aggregate exposure cap (AGG_CAP_PCT) the way run_kelly_backtest.py
already sweeps the per-trade position cap -- we tested the two extremes
(50% capped vs. 100%/100%/100% uncapped stress test) but never located
where the risk-adjusted optimum actually sits in between. Holds fraction
(quarter-Kelly), the 3% per-trade cap, and the 25% per-category cap fixed;
only the aggregate cap moves. Also sweeps the per-category cap on its own
axis, holding aggregate at 50%, since the live scan showed the category cap
(not the aggregate cap) was what actually turned away demand in "other".
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_kelly_backtest import load, run_sim, DATA_DIR, MAX_POS_PCT, CAT_CAP_PCT, AGG_CAP_PCT


def main():
    maker_trades = load("trades_maker.csv")

    print("=== Aggregate cap sweep (fraction=0.25, per-trade cap=3%, per-category cap=25% fixed) ===")
    agg_results = []
    for agg in [0.10, 0.20, 0.30, 0.40, 0.50, 0.65, 0.80, 1.00]:
        res = run_sim([dict(r) for r in maker_trades], 0.25, agg_cap_pct=agg)
        agg_results.append({"agg_cap_pct": agg, **res})
        print(f"agg_cap={agg:<6.2f} final=${res['final_equity']:>10,.0f}  CAGR={res['cagr_pct']:>6.1f}%  "
              f"MaxDD={res['max_drawdown_pct']:>5.1f}%  Sharpe={res['sharpe']}  "
              f"taken={res['n_taken']}  skip_cap={res['n_skip_capital']}  flips={res['n_flips_taken']}")

    print("\n=== Per-category cap sweep (fraction=0.25, per-trade cap=3%, aggregate cap=50% fixed) ===")
    cat_results = []
    for cat in [0.10, 0.15, 0.20, 0.25, 0.35, 0.50, 0.75, 1.00]:
        res = run_sim([dict(r) for r in maker_trades], 0.25, cat_cap_pct=cat)
        cat_results.append({"cat_cap_pct": cat, **res})
        print(f"cat_cap={cat:<6.2f} final=${res['final_equity']:>10,.0f}  CAGR={res['cagr_pct']:>6.1f}%  "
              f"MaxDD={res['max_drawdown_pct']:>5.1f}%  Sharpe={res['sharpe']}  "
              f"taken={res['n_taken']}  skip_cap={res['n_skip_capital']}  flips={res['n_flips_taken']}")

    print(f"\n(baseline recommended config: agg={AGG_CAP_PCT}, cat={CAT_CAP_PCT}, pos={MAX_POS_PCT})")

    out_path = os.path.join(DATA_DIR, "kelly_agg_cat_cap_sweep.json")
    with open(out_path, "w") as f:
        json.dump({"agg_sweep": agg_results, "cat_sweep": cat_results}, f, indent=2)
    print(f"saved {out_path}")


if __name__ == "__main__":
    main()
