"""Checkpoint 4: generate strategy positions/trades and report descriptive
stats (NOT the full rigorous backtest -- that's checkpoint 5: walk-forward
IS/validation/holdout split, HAC t-stats, benchmarks, bootstrap
significance). This is a sanity check that the engine behaves sensibly
before that fuller evaluation.

Run as: python -m spx_egarch_gex.strategy.run_signals
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from spx_egarch_gex import config
from spx_egarch_gex.strategy.costs import apply_costs
from spx_egarch_gex.strategy.engine import generate_positions
from spx_egarch_gex.strategy.signals import build_signal_frame


def trade_stats(trades, strategy_name: str) -> str:
    sub = [t for t in trades if t.strategy == strategy_name]
    if not sub:
        return f"{strategy_name}: no trades"
    n = len(sub)
    win_rate = sum(1 for t in sub if t.cum_return * t.direction > 0) / n
    avg_hold = np.mean([t.days_held for t in sub])
    avg_ret = np.mean([t.cum_return * t.direction for t in sub])  # in direction-of-trade terms
    reasons = pd.Series([t.exit_reason for t in sub]).value_counts()
    return (
        f"{strategy_name}: n_trades={n}  win_rate={win_rate:.1%}  "
        f"avg_days_held={avg_hold:.1f}  avg_trade_return={avg_ret*100:.3f}%\n"
        f"  exit reasons: {dict(reasons)}"
    )


def main():
    df = build_signal_frame()
    sub = df.loc[config.GEX_HISTORY_START:]

    position, trades = generate_positions(sub)
    costed = apply_costs(position, sub["ret"])

    report_lines = []
    report_lines.append(f"Sample: {sub.index.min().date()} -> {sub.index.max().date()}  (n={len(sub)})")
    report_lines.append(f"Regime base rates: {dict(sub['regime'].value_counts())}")
    report_lines.append("")

    report_lines.append(f"Total trades: {len(trades)}")
    report_lines.append(trade_stats(trades, "mean_reversion"))
    report_lines.append(trade_stats(trades, "vol_breakout"))
    report_lines.append("")

    frac_in_market = (position != 0).mean()
    avg_abs_position = position.abs().mean()
    report_lines.append(f"Fraction of days with a position: {frac_in_market:.1%}")
    report_lines.append(f"Mean |position| (vol-targeted notional, when in market): "
                        f"{position[position!=0].abs().mean():.2f}x")
    report_lines.append(f"Max |position|: {position.abs().max():.2f}x")
    report_lines.append("")

    ann_factor = np.sqrt(252)
    gross_mean = costed["gross_ret"].mean() * 252
    gross_vol = costed["gross_ret"].std() * ann_factor
    net_mean = costed["net_ret"].mean() * 252
    net_vol = costed["net_ret"].std() * ann_factor
    total_cost_drag = (costed["turnover_cost"] + costed["financing_cost"]).sum()
    report_lines.append("Preliminary (non-rigorous, whole-sample) return stats -- see checkpoint 5 for the real backtest:")
    report_lines.append(f"  gross: ann_return={gross_mean*100:.2f}%  ann_vol={gross_vol*100:.2f}%  "
                        f"sharpe={gross_mean/gross_vol:.2f}" if gross_vol > 0 else "  gross: n/a")
    report_lines.append(f"  net:   ann_return={net_mean*100:.2f}%  ann_vol={net_vol*100:.2f}%  "
                        f"sharpe={net_mean/net_vol:.2f}" if net_vol > 0 else "  net: n/a")
    report_lines.append(f"  total cost drag over sample: {total_cost_drag*100:.2f}% (cumulative, unlevered-return terms)")

    report = "\n".join(report_lines)
    print(report)

    out_path = config.RESULTS_DIR / "checkpoint4_strategy_sanity_check.txt"
    out_path.write_text(report + "\n")
    print(f"\nWrote report to {out_path}")

    costed.to_csv(config.PROCESSED_DIR / "strategy_returns_preliminary.csv")
    print("Wrote position/return series to data/processed/strategy_returns_preliminary.csv")


if __name__ == "__main__":
    main()
