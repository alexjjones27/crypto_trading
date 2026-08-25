"""Diagnose why the checkpoint-4 preliminary result is weak/negative, before
committing to checkpoint 5's full backtest with these exact rules.

Three angles:
1. Trade-level P&L distributions for each sub-strategy (are losses driven
   by a few outliers or a broadly weak edge?).
2. Mean-reversion sensitivity grid over (lookback, entry_z) -- is there a
   parameter region with a real edge, or is z-score reversion just not
   there in this regime/sample regardless of tuning?
3. Vol-breakout: momentum (follow) vs contrarian (fade) entry direction.
   Motivated by checkpoint 3's finding that negative-gamma return
   autocorrelation was MORE negative (more reversal-like, corr=-0.234)
   than positive-gamma (-0.052) -- the opposite of the momentum
   hypothesis. If that's real, fading the breakout (not following it)
   might be the better-fitting rule, not just noise to tune away.

This is diagnostic/exploratory, run on the whole GEX-covered sample (not
IS/validation/holdout split) -- explicitly NOT the final parameter choice.
Whatever comes out of this gets locked in BEFORE checkpoint 5 evaluates it
walk-forward on the proper split, same as checkpoint 4's original
untouched rules were.

Run as: python -m spx_egarch_gex.strategy.run_diagnostics
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from spx_egarch_gex import config
from spx_egarch_gex.strategy.engine import generate_positions
from spx_egarch_gex.strategy.signals import build_signal_frame


def trade_log_df(trades) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "strategy": t.strategy,
            "direction": t.direction,
            "entry_date": t.entry_date,
            "exit_date": t.exit_date,
            "days_held": t.days_held,
            "trade_return": t.cum_return * t.direction,  # in direction-of-trade terms
            "exit_reason": t.exit_reason,
        }
        for t in trades
    ])


def plot_trade_distributions(tl: pd.DataFrame, path):
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.5))
    for ax, strat in zip(axes, ["mean_reversion", "vol_breakout"]):
        sub = tl.loc[tl.strategy == strat, "trade_return"] * 100
        if sub.empty:
            continue
        ax.hist(sub, bins=30, color="#2a9d8f" if strat == "mean_reversion" else "#e76f51")
        ax.axvline(0, color="black", linewidth=1)
        ax.axvline(sub.mean(), color="red", linewidth=1, linestyle="--", label=f"mean={sub.mean():.2f}%")
        ax.set_title(f"{strat} trade returns (n={len(sub)})")
        ax.set_xlabel("trade return %")
        ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def mr_sensitivity_grid(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for lookback in (3, 5, 10, 20):
        for entry_z in (1.0, 1.5, 2.0, 2.5):
            cfg_backup = (config.MR_LOOKBACK_DAYS, config.MR_ENTRY_Z)
            config.MR_LOOKBACK_DAYS, config.MR_ENTRY_Z = lookback, entry_z
            try:
                # rebuild mr_z with the trial lookback (breakout signal untouched)
                trial_df = build_signal_frame().loc[config.GEX_HISTORY_START:]
                _, trades = generate_positions(trial_df)
                tl = trade_log_df(trades)
                mr = tl.loc[tl.strategy == "mean_reversion", "trade_return"]
                rows.append({
                    "lookback": lookback, "entry_z": entry_z, "n_trades": len(mr),
                    "win_rate": (mr > 0).mean() if len(mr) else np.nan,
                    "mean_ret_pct": mr.mean() * 100 if len(mr) else np.nan,
                    "t_stat": (mr.mean() / mr.std() * np.sqrt(len(mr))) if len(mr) > 5 else np.nan,
                })
            finally:
                config.MR_LOOKBACK_DAYS, config.MR_ENTRY_Z = cfg_backup
    return pd.DataFrame(rows)


def breakout_direction_test(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for label, flip in [("momentum (follow)", 1), ("contrarian (fade)", -1)]:
        trial_df = df.copy()
        trial_df["breakout_sigma"] = trial_df["breakout_sigma"] * flip
        _, trades = generate_positions(trial_df)
        tl = trade_log_df(trades)
        brk = tl.loc[tl.strategy == "vol_breakout", "trade_return"]
        rows.append({
            "direction": label, "n_trades": len(brk),
            "win_rate": (brk > 0).mean() if len(brk) else np.nan,
            "mean_ret_pct": brk.mean() * 100 if len(brk) else np.nan,
            "t_stat": (brk.mean() / brk.std() * np.sqrt(len(brk))) if len(brk) > 5 else np.nan,
        })
    return pd.DataFrame(rows)


def main():
    df = build_signal_frame()
    sub = df.loc[config.GEX_HISTORY_START:]
    _, trades = generate_positions(sub)
    tl = trade_log_df(trades)
    tl.to_csv(config.PROCESSED_DIR / "strategy_trade_log.csv", index=False)

    report_lines = []
    report_lines.append("=== Trade-level P&L summary ===")
    for strat in ["mean_reversion", "vol_breakout"]:
        s = tl.loc[tl.strategy == strat, "trade_return"]
        report_lines.append(
            f"{strat}: n={len(s)}  mean={s.mean()*100:.3f}%  median={s.median()*100:.3f}%  "
            f"std={s.std()*100:.3f}%  min={s.min()*100:.2f}%  max={s.max()*100:.2f}%  "
            f"skew={s.skew():.2f}"
        )
    report_lines.append("")

    plot_trade_distributions(tl, config.RESULTS_DIR / "trade_return_distributions.png")
    report_lines.append(f"Wrote {config.RESULTS_DIR}/trade_return_distributions.png")
    report_lines.append("")

    report_lines.append("=== Mean-reversion sensitivity: (lookback, entry_z) grid ===")
    grid = mr_sensitivity_grid(sub)
    report_lines.append(grid.to_string(index=False))
    report_lines.append("")
    best = grid.loc[grid["mean_ret_pct"].idxmax()]
    report_lines.append(f"Best mean_ret_pct in grid: lookback={best['lookback']:.0f} entry_z={best['entry_z']:.1f} "
                        f"mean_ret={best['mean_ret_pct']:.3f}% t_stat={best['t_stat']:.2f} n={best['n_trades']:.0f}")
    report_lines.append("(NOTE: this is exploratory diagnosis on the whole sample, not a walk-forward-selected "
                        "parameter -- picking 'best of grid' here would be in-sample overfitting; the point is "
                        "to see whether ANY region of this space shows a real edge before concluding there isn't one.)")
    report_lines.append("")

    report_lines.append("=== Vol-breakout: momentum vs contrarian entry direction ===")
    bd = breakout_direction_test(sub)
    report_lines.append(bd.to_string(index=False))

    report = "\n".join(report_lines)
    print(report)

    out_path = config.RESULTS_DIR / "checkpoint4b_strategy_diagnostics.txt"
    out_path.write_text(report + "\n")
    print(f"\nWrote report to {out_path}")


if __name__ == "__main__":
    main()
