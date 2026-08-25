"""EGARCH(1,1) fitting and residual diagnostics for SPX log returns.

Returns are scaled by 100 (percent) before fitting, which is the standard
`arch`-package convention for numerical stability of the MLE optimizer; all
outputs are converted back to the original (fractional log-return) scale.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from arch import arch_model
from arch.univariate.base import ARCHModelResult
from statsmodels.stats.diagnostic import acorr_ljungbox, het_arch

RETURN_SCALE = 100.0


def fit_egarch(
    returns: pd.Series, dist: str = "t", mean: str = "Constant"
) -> ARCHModelResult:
    """Fit EGARCH(1,1) (p=1, o=1, q=1) on `returns` (fractional log returns)."""
    scaled = returns.dropna() * RETURN_SCALE
    am = arch_model(scaled, mean=mean, vol="EGARCH", p=1, o=1, q=1, dist=dist)
    return am.fit(disp="off")


@dataclass
class DiagnosticResult:
    dist: str
    aic: float
    bic: float
    loglik: float
    params: pd.Series
    std_resid: pd.Series
    ljung_box_resid: pd.DataFrame  # Ljung-Box on standardized residuals (levels)
    ljung_box_resid_sq: pd.DataFrame  # Ljung-Box on squared standardized residuals
    arch_lm_stat: float
    arch_lm_pvalue: float
    resid_skew: float
    resid_kurtosis: float


def diagnose(res: ARCHModelResult, dist: str, lb_lags: tuple[int, ...] = (5, 10, 20)) -> DiagnosticResult:
    """Compute the standard EGARCH-adequacy diagnostics for a fitted model.

    - Ljung-Box on standardized residuals: tests whether the mean equation
      has left autocorrelation (should NOT reject, i.e. large p-values).
    - Ljung-Box on squared standardized residuals: tests whether the
      volatility equation has left autocorrelation in the variance (should
      NOT reject; this is the key test of whether EGARCH(1,1) is an
      adequate order for the conditional variance).
    - ARCH-LM on standardized residuals: alternative test for remaining
      ARCH effects; should NOT reject.
    - skew/kurtosis of standardized residuals, to check the chosen
      innovation distribution's shape assumption isn't badly violated
      even after accounting for its own skew/df parameters.
    """
    std_resid = res.std_resid.dropna()

    lb_levels = acorr_ljungbox(std_resid, lags=list(lb_lags), return_df=True)
    lb_sq = acorr_ljungbox(std_resid**2, lags=list(lb_lags), return_df=True)

    arch_lm_stat, arch_lm_pvalue, _, _ = het_arch(std_resid, nlags=12)

    return DiagnosticResult(
        dist=dist,
        aic=res.aic,
        bic=res.bic,
        loglik=res.loglikelihood,
        params=res.params,
        std_resid=std_resid,
        ljung_box_resid=lb_levels,
        ljung_box_resid_sq=lb_sq,
        arch_lm_stat=arch_lm_stat,
        arch_lm_pvalue=arch_lm_pvalue,
        resid_skew=float(std_resid.skew()),
        resid_kurtosis=float(std_resid.kurtosis()),  # excess kurtosis (Fisher)
    )


def compare_distributions(
    returns: pd.Series, dists: tuple[str, ...] = ("normal", "t", "skewt")
) -> dict[str, DiagnosticResult]:
    results = {}
    for dist in dists:
        res = fit_egarch(returns, dist=dist)
        results[dist] = diagnose(res, dist)
    return results


def summarize_comparison(results: dict[str, DiagnosticResult]) -> str:
    lines = []
    lines.append(f"{'dist':8s} {'AIC':>12s} {'BIC':>12s} {'LogLik':>12s} "
                 f"{'LB(20)_p':>10s} {'LB2(20)_p':>10s} {'ARCH-LM_p':>10s} "
                 f"{'skew':>8s} {'exkurt':>8s}")
    for dist, d in results.items():
        lb_p = d.ljung_box_resid["lb_pvalue"].iloc[-1]
        lb2_p = d.ljung_box_resid_sq["lb_pvalue"].iloc[-1]
        lines.append(
            f"{dist:8s} {d.aic:12.2f} {d.bic:12.2f} {d.loglik:12.2f} "
            f"{lb_p:10.4f} {lb2_p:10.4f} {d.arch_lm_pvalue:10.4f} "
            f"{d.resid_skew:8.3f} {d.resid_kurtosis:8.3f}"
        )
    return "\n".join(lines)
