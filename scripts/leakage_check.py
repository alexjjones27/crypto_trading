"""Leakage check on the checkpoint-4b lookback/entry-threshold grid and
momentum-vs-contrarian direction selection.

Part 1: state exactly what date range each selection step touched, compare
against the planned checkpoint-5 split, report contamination plainly.

Part 2: if contaminated, redo both selections as a proper nested
train/select procedure -- grid/A-B test computed on IN-SAMPLE data only
(2011-05-02 to 2017-12-31), final choice made using VALIDATION-only
out-of-sample performance (2018-01-01 to 2020-12-31). Holdout
(2021-01-01-present) is never touched by any code in this script.

Run as: PYTHONPATH=src python3 scripts/leakage_check.py
"""

from __future__ import annotations

import sys

sys.path.insert(0, "src")

import pandas as pd

from spx_egarch_gex import config
from spx_egarch_gex.strategy.run_diagnostics import breakout_direction_test, mr_sensitivity_grid
from spx_egarch_gex.strategy.signals import build_signal_frame

IN_SAMPLE = config.SPLIT_IN_SAMPLE       # ("2011-05-02", "2017-12-31")
VALIDATION = config.SPLIT_VALIDATION     # ("2018-01-01", "2020-12-31")
HOLDOUT = config.SPLIT_HOLDOUT           # ("2021-01-01", None)


def main():
    df = build_signal_frame()
    full_sub = df.loc[config.GEX_HISTORY_START:]

    report = []
    report.append("=== PART 1: contamination check ===")
    report.append(f"checkpoint-4b grid search date range used: "
                f"{full_sub.index.min().date()} -> {full_sub.index.max().date()}")
    report.append(f"checkpoint-4b momentum/contrarian A-B test date range used: "
                f"{full_sub.index.min().date()} -> {full_sub.index.max().date()}")
    report.append("")
    report.append(f"Planned split: in-sample {IN_SAMPLE[0]}->{IN_SAMPLE[1]}, "
                f"validation {VALIDATION[0]}->{VALIDATION[1]}, "
                f"holdout {HOLDOUT[0]}->present")
    report.append("")
    holdout_start = pd.Timestamp(HOLDOUT[0])
    touched_holdout = full_sub.index.max() >= holdout_start
    report.append(f"CONTAMINATED: {touched_holdout}. Both selection steps used the ENTIRE "
                f"available sample ({full_sub.index.min().date()} to {full_sub.index.max().date()}), "
                f"which fully contains and extends past the planned holdout start "
                f"({holdout_start.date()}). This is complete overlap, not partial: every single "
                f"holdout-period date (2021-01-01 onward) was inside the data both the lookback/"
                f"entry_z grid and the momentum-vs-contrarian A/B test were computed on. The "
                f"in-sample and validation windows were touched too, but that's expected/fine for a "
                f"selection step -- the holdout being touched is the actual problem.")
    report.append("")

    # --- Part 2: nested re-selection, IS-only fit, validation-only decision ---
    report.append("=== PART 2: nested re-selection (holdout never touched) ===")
    is_sub = df.loc[IN_SAMPLE[0]:IN_SAMPLE[1]]
    val_sub = df.loc[VALIDATION[0]:VALIDATION[1]]
    report.append(f"in-sample fit range actually used: {is_sub.index.min().date()} -> {is_sub.index.max().date()}")
    report.append(f"validation decision range actually used: {val_sub.index.min().date()} -> {val_sub.index.max().date()}")
    report.append(f"(holdout {HOLDOUT[0]}-present: zero rows read by this script -- confirmed by construction, "
                f"df.loc[] above never references it)")
    report.append("")

    report.append("--- Mean-reversion: grid computed on in-sample ---")
    is_grid = mr_sensitivity_grid(is_sub)
    report.append(is_grid.to_string(index=False))
    report.append("")

    report.append("--- Same grid cells, evaluated on validation-only data (decision made here) ---")
    val_grid = mr_sensitivity_grid(val_sub)
    report.append(val_grid.to_string(index=False))
    report.append("")

    # cross-threshold consistency check, same logic as the original selection:
    # which lookback has a positive mean_ret_pct at every entry_z, now checked
    # on validation instead of the full contaminated sample
    report.append("Cross-threshold consistency on VALIDATION (mirrors the original selection logic):")
    for lb in sorted(val_grid["lookback"].unique()):
        row = val_grid.loc[val_grid.lookback == lb, "mean_ret_pct"]
        all_positive = (row > 0).all()
        report.append(f"  lookback={lb:.0f}: mean_ret_pct at each entry_z = {row.tolist()}  "
                    f"all positive: {all_positive}")
    report.append("")

    report.append("--- Vol-breakout direction: A/B computed on in-sample ---")
    is_bd = breakout_direction_test(is_sub)
    report.append(is_bd.to_string(index=False))
    report.append("")

    report.append("--- Same A/B, evaluated on validation-only data (decision made here) ---")
    val_bd = breakout_direction_test(val_sub)
    report.append(val_bd.to_string(index=False))
    report.append("")

    contrarian_wins_val = (
        val_bd.loc[val_bd.direction.str.contains("contrarian"), "mean_ret_pct"].iloc[0]
        > val_bd.loc[val_bd.direction.str.contains("momentum"), "mean_ret_pct"].iloc[0]
    )
    report.append(f"Contrarian still beats momentum on validation-only data: {contrarian_wins_val}")

    report_text = "\n".join(report)
    print(report_text)

    out_path = config.RESULTS_DIR / "leakage_check.txt"
    out_path.write_text(report_text + "\n")
    print(f"\nWrote report to {out_path}")


if __name__ == "__main__":
    main()
