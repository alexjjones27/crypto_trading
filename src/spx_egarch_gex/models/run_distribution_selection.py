"""Checkpoint 2, step A: choose the EGARCH innovation distribution.

Fit is on all data available through the end of the in-sample period only
(config.SPLIT_IN_SAMPLE[1]) -- using validation/holdout data to pick the
distribution would itself be a form of look-ahead into the backtest.
Note this fit uses the full 1990- price history up to that cutoff, not just
the GEX-constrained in-sample window, since distributional shape of SPX
returns doesn't depend on GEX and more data means a better-identified fit.

Run as: python -m spx_egarch_gex.models.run_distribution_selection
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

from spx_egarch_gex import config
from spx_egarch_gex.models.egarch import compare_distributions, summarize_comparison


def qq_plot(std_resid: pd.Series, dist: str, params: pd.Series, path):
    fig, ax = plt.subplots(figsize=(5, 5))
    if dist == "normal":
        stats.probplot(std_resid, dist="norm", plot=ax)
    elif dist == "t":
        nu = params["nu"]
        stats.probplot(std_resid, dist="t", sparams=(nu,), plot=ax)
    elif dist == "skewt":
        # arch's Hansen skew-t isn't a scipy distribution; compare against
        # a standard t with matching df (its "eta" parameter) as an
        # approximation for the plot, noting the skew ("lambda") separately.
        nu = params["eta"]
        stats.probplot(std_resid, dist="t", sparams=(nu,), plot=ax)
    ax.set_title(f"QQ plot: standardized residuals vs {dist}")
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def main():
    panel = pd.read_csv(config.PROCESSED_DIR / "panel.csv", index_col="date", parse_dates=["date"])
    returns = panel["spx_log_ret"].dropna()
    in_sample_end = config.SPLIT_IN_SAMPLE[1]
    sample = returns.loc[config.EGARCH_DIAGNOSTIC_START : in_sample_end]

    print(f"Distribution-selection sample: {sample.index.min().date()} -> {sample.index.max().date()} "
          f"(n={len(sample)})")

    results = compare_distributions(sample, dists=("normal", "t", "skewt"))

    report_lines = []
    report_lines.append(f"Sample: {sample.index.min().date()} -> {sample.index.max().date()} (n={len(sample)})")
    report_lines.append("")
    report_lines.append(summarize_comparison(results))
    report_lines.append("")
    report_lines.append("Ljung-Box on standardized residuals (levels), full table, per distribution:")
    for dist, d in results.items():
        report_lines.append(f"\n-- {dist} --")
        report_lines.append(f"params:\n{d.params.to_string()}")
        report_lines.append(f"\nLjung-Box (levels):\n{d.ljung_box_resid.to_string()}")
        report_lines.append(f"\nLjung-Box (squared):\n{d.ljung_box_resid_sq.to_string()}")
        report_lines.append(f"\nARCH-LM stat={d.arch_lm_stat:.4f} p={d.arch_lm_pvalue:.4f}")

    report = "\n".join(report_lines)
    print(report)

    out_path = config.RESULTS_DIR / "checkpoint2_distribution_selection.txt"
    out_path.write_text(report + "\n")

    for dist, d in results.items():
        qq_plot(d.std_resid, dist, d.params, config.RESULTS_DIR / f"qq_{dist}.png")

    print(f"\nWrote report to {out_path}")
    print(f"Wrote QQ plots to {config.RESULTS_DIR}/qq_*.png")


if __name__ == "__main__":
    main()
