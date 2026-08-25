"""Checkpoint 2, step B: walk-forward EGARCH(1,1) with skew-t innovations,
comparing rolling vs expanding re-estimation windows.

Both variants refit (re-optimize) EVERY trading day using only data through
t-1, i.e. true daily walk-forward, not a periodic-refit approximation --
affordable here since a single EGARCH(1,1) fit takes ~10-100ms.

Run as: python -m spx_egarch_gex.models.run_walk_forward_comparison
"""

from __future__ import annotations

import time

import pandas as pd
from statsmodels.stats.diagnostic import acorr_ljungbox, het_arch

from spx_egarch_gex import config
from spx_egarch_gex.models.walk_forward import forecast_eval, walk_forward_egarch

DIST = "skewt"
ROLLING_WINDOW = 1260  # ~5 trading years
MIN_OBS = 500


def evaluate_variant(name: str, result, returns: pd.Series) -> str:
    lines = [f"--- {name} ---"]
    lines.append(f"n_forecasts={len(result.cond_vol)}  n_refits={result.n_refits}")
    lines.append(
        f"cond_vol (annualized %) mean={result.cond_vol.mean()*100*(252**0.5):.2f} "
        f"min={result.cond_vol.min()*100*(252**0.5):.2f} "
        f"max={result.cond_vol.max()*100*(252**0.5):.2f}"
    )

    ev = forecast_eval(result.cond_vol, returns)
    lines.append(f"QLIKE={ev['qlike']:.4f}  MSE={ev['mse']:.3e}  n={ev['n']}")

    sr = result.std_resid
    lines.append(f"std_resid: mean={sr.mean():.4f} std={sr.std():.4f} "
                 f"skew={sr.skew():.4f} exkurt={sr.kurtosis():.4f}")

    lb = acorr_ljungbox(sr, lags=[20], return_df=True)
    lb2 = acorr_ljungbox(sr**2, lags=[20], return_df=True)
    arch_lm_stat, arch_lm_p, _, _ = het_arch(sr, nlags=12)
    lines.append(f"Ljung-Box(20) levels p={lb['lb_pvalue'].iloc[0]:.4f}  "
                 f"squared p={lb2['lb_pvalue'].iloc[0]:.4f}  "
                 f"ARCH-LM p={arch_lm_p:.4f}")
    return "\n".join(lines)


def main():
    panel = pd.read_csv(config.PROCESSED_DIR / "panel.csv", index_col="date", parse_dates=["date"])
    returns = panel["spx_log_ret"].dropna()

    report_lines = []
    report_lines.append(f"Full series: {returns.index.min().date()} -> {returns.index.max().date()} "
                        f"(n={len(returns)})")
    report_lines.append(f"Distribution: {DIST}, daily refit (refit_frequency=1), min_obs={MIN_OBS}")
    report_lines.append(f"Rolling window size: {ROLLING_WINDOW} trading days (~5y)")
    report_lines.append("")

    t0 = time.time()
    exp_result = walk_forward_egarch(
        returns, dist=DIST, window_type="expanding", refit_frequency=1, min_obs=MIN_OBS
    )
    t_exp = time.time() - t0
    print(f"expanding done in {t_exp:.1f}s")

    t0 = time.time()
    roll_result = walk_forward_egarch(
        returns, dist=DIST, window_type="rolling", window_size=ROLLING_WINDOW,
        refit_frequency=1, min_obs=MIN_OBS,
    )
    t_roll = time.time() - t0
    print(f"rolling done in {t_roll:.1f}s")

    report_lines.append(f"[expanding fit time: {t_exp:.1f}s, rolling fit time: {t_roll:.1f}s]")
    report_lines.append("")
    report_lines.append(evaluate_variant("expanding", exp_result, returns))
    report_lines.append("")
    report_lines.append(evaluate_variant(f"rolling (w={ROLLING_WINDOW})", roll_result, returns))

    report = "\n".join(report_lines)
    print(report)

    out_path = config.RESULTS_DIR / "checkpoint2_walk_forward_comparison.txt"
    out_path.write_text(report + "\n")
    print(f"\nWrote report to {out_path}")

    # Persist both series; downstream code picks one, but keep both for
    # the record / robustness checks.
    exp_result.cond_vol.to_frame("cond_vol_expanding").join(
        exp_result.std_resid.to_frame("std_resid_expanding"), how="outer"
    ).to_csv(config.PROCESSED_DIR / "egarch_forecasts_expanding.csv")

    roll_result.cond_vol.to_frame("cond_vol_rolling").join(
        roll_result.std_resid.to_frame("std_resid_rolling"), how="outer"
    ).to_csv(config.PROCESSED_DIR / "egarch_forecasts_rolling.csv")
    print("Wrote forecast series to data/processed/egarch_forecasts_{expanding,rolling}.csv")


if __name__ == "__main__":
    main()
