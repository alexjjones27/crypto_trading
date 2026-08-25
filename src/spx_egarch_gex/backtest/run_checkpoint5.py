"""Checkpoint 5: the rigorous walk-forward backtest.

Uses the exact rules locked in after the checkpoint-4b leakage check
(config.py's MR_LOOKBACK_DAYS=3, vol-breakout momentum direction) --
nothing tuned here, this is evaluation only.

Produces, for in-sample / validation / holdout / full sample:
  - strategy (regime-aware) net & gross returns
  - regime-blind benchmark (same rules, no regime gate)
  - buy-and-hold SPX
  - HAC (Newey-West) t-stats on daily returns
  - circular block-bootstrap CI/p-value on daily returns
  - paired block-bootstrap test on (regime-aware - regime-blind) returns,
    the direct test of whether regime-gating adds value
  - explicit IS -> validation -> holdout degradation check

Run as: PYTHONPATH=src python3 -m spx_egarch_gex.backtest.run_checkpoint5
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from spx_egarch_gex import config
from spx_egarch_gex.backtest.metrics import summary
from spx_egarch_gex.stats.inference import circular_block_bootstrap_mean_test, newey_west_tstat
from spx_egarch_gex.strategy.costs import apply_costs
from spx_egarch_gex.strategy.engine import generate_positions
from spx_egarch_gex.strategy.signals import build_signal_frame

SPLITS = {
    "in_sample": config.SPLIT_IN_SAMPLE,
    "validation": config.SPLIT_VALIDATION,
    "holdout": (config.SPLIT_HOLDOUT[0], None),
}


def build_all_series() -> pd.DataFrame:
    df = build_signal_frame()
    sub = df.loc[config.GEX_HISTORY_START:]

    pos_aware, trades_aware = generate_positions(sub, regime_blind=False)
    pos_blind, trades_blind = generate_positions(sub, regime_blind=True)

    costed_aware = apply_costs(pos_aware, sub["ret"])
    costed_blind = apply_costs(pos_blind, sub["ret"])

    out = pd.DataFrame(index=sub.index)
    out["bh_ret"] = sub["ret"]
    out["aware_gross"] = costed_aware["gross_ret"]
    out["aware_net"] = costed_aware["net_ret"]
    out["blind_gross"] = costed_blind["gross_ret"]
    out["blind_net"] = costed_blind["net_ret"]
    out["aware_position"] = costed_aware["position"]
    out["blind_position"] = costed_blind["position"]

    return out, trades_aware, trades_blind


def split_slice(df: pd.DataFrame, split: tuple[str, str | None]) -> pd.DataFrame:
    start, end = split
    return df.loc[start:end] if end else df.loc[start:]


def report_split(name: str, seg: pd.DataFrame) -> list[str]:
    lines = [f"--- {name}: {seg.index.min().date()} -> {seg.index.max().date()} (n={len(seg)}) ---"]

    for col, label in [("bh_ret", "Buy & hold"), ("aware_gross", "Strategy (gross)"),
                        ("aware_net", "Strategy (net)"), ("blind_net", "Regime-blind (net)")]:
        s = summary(seg[col])
        lines.append(f"  {label:20s}: ann_ret={s['ann_return']*100:7.2f}%  ann_vol={s['ann_vol']*100:6.2f}%  "
                    f"sharpe={s['sharpe']:6.2f}  max_dd={s['max_drawdown']*100:7.2f}%")

    nw = newey_west_tstat(seg["aware_net"])
    lines.append(f"  HAC (Newey-West) t-stat on strategy net daily return: "
                f"mean={nw['mean']*100:.4f}%  t={nw['tstat']:.3f}  p={nw['pvalue']:.4f}  (lags={nw['lags']})")

    boot = circular_block_bootstrap_mean_test(seg["aware_net"], n_boot=5000, block_size=20)
    lines.append(f"  Block-bootstrap on strategy net daily return: mean={boot['observed_mean']*100:.4f}%  "
                f"95% CI=[{boot['ci_lo']*100:.4f}%, {boot['ci_hi']*100:.4f}%]  p={boot['p_value']:.4f}")

    diff = (seg["aware_net"] - seg["blind_net"]).dropna()
    diff_boot = circular_block_bootstrap_mean_test(diff, n_boot=5000, block_size=20)
    lines.append(f"  Block-bootstrap on (regime-aware - regime-blind) daily return diff: "
                f"mean={diff_boot['observed_mean']*100:.4f}%  "
                f"95% CI=[{diff_boot['ci_lo']*100:.4f}%, {diff_boot['ci_hi']*100:.4f}%]  "
                f"p={diff_boot['p_value']:.4f}")
    lines.append(f"  -> regime-gating {'ADDS' if diff_boot['observed_mean'] > 0 else 'SUBTRACTS'} value here; "
                f"{'statistically significant' if diff_boot['p_value'] < 0.05 else 'NOT statistically significant'} at 5%")

    return lines


def main():
    all_series, trades_aware, trades_blind = build_all_series()

    report = []
    report.append("=== Checkpoint 5: walk-forward backtest ===")
    report.append(f"Rules locked in post-leakage-check: MR_LOOKBACK_DAYS={config.MR_LOOKBACK_DAYS}, "
                f"MR_ENTRY_Z={config.MR_ENTRY_Z}, vol-breakout=momentum, "
                f"BRK_ENTRY_SIGMA={config.BRK_ENTRY_SIGMA}")
    report.append(f"Costs: {config.TRANSACTION_COST_BPS}bps/turnover + "
                f"{config.FINANCING_SPREAD_ANNUAL*100:.1f}%/yr financing on leverage>1x")
    report.append("")

    splits_data = {}
    for name, split in SPLITS.items():
        seg = split_slice(all_series, split)
        splits_data[name] = seg
        report.extend(report_split(name, seg))
        report.append("")

    report.extend(report_split("full_sample", all_series))
    report.append("")

    # --- OOS degradation check ---
    report.append("=== In-sample -> validation -> holdout degradation ===")
    is_sharpe = summary(splits_data["in_sample"]["aware_net"])["sharpe"]
    val_sharpe = summary(splits_data["validation"]["aware_net"])["sharpe"]
    hold_sharpe = summary(splits_data["holdout"]["aware_net"])["sharpe"]
    report.append(f"Net Sharpe: in-sample={is_sharpe:.2f}  validation={val_sharpe:.2f}  holdout={hold_sharpe:.2f}")
    if val_sharpe < is_sharpe - 0.3 or hold_sharpe < is_sharpe - 0.3:
        report.append("FLAG: material Sharpe degradation from in-sample to validation/holdout (>0.3 drop).")
    if np.sign(is_sharpe) != np.sign(hold_sharpe) and abs(hold_sharpe) > 0.05:
        report.append("FLAG: Sharpe sign flips between in-sample and holdout.")
    report.append("")

    report_text = "\n".join(report)
    print(report_text)

    out_path = config.RESULTS_DIR / "checkpoint5_backtest.txt"
    out_path.write_text(report_text + "\n")
    print(f"\nWrote report to {out_path}")

    all_series.to_csv(config.PROCESSED_DIR / "checkpoint5_all_series.csv")
    print("Wrote full daily series to data/processed/checkpoint5_all_series.csv")


if __name__ == "__main__":
    main()
