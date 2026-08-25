"""True walk-forward EGARCH(1,1) re-estimation.

Every forecast for day t uses only information available through day t-1:
the model is refit (or, between refit points, its variance recursion is
re-evaluated with fixed parameters) on a window ending at t-1, and the
one-step-ahead forecast is produced *before* day t's return is observed.
This is what makes the resulting conditional-vol series usable downstream
without look-ahead bias.

Two window disciplines are supported:
- "expanding": refit on all data from the start of the series through t-1.
- "rolling":   refit on the last `window_size` observations through t-1.

`refit_frequency` controls how often the MLE is actually re-optimized
(1 = every day = the gold standard, affordable here since a single
EGARCH(1,1) fit/fix+forecast takes ~10-100ms). On non-refit days the
previous fit's parameters are held fixed and the recursion is simply
re-evaluated on the extended data (via `ARCHModel.fix`), which is cheap and
still uses all realized returns through t-1.

Some daily MLE refits land on a degenerate solution -- e.g. beta[1]
pinned at/near the EGARCH stationarity boundary (|beta|=1), or a
parameter blown out to an implausible scale -- while scipy's optimizer
still reports `convergence_flag == 0`. These aren't rare enough to ignore
(observed on both window types, concentrated in the smaller-sample early
1990s): the resulting one-step variance forecast can be many orders of
magnitude off, which silently corrupts every downstream mean/std
statistic even after filtering literal inf/nan. Each day's *candidate*
forecast is therefore sanity-checked (plausible annualized-vol range +
stationarity), and a refit that fails the check is rejected in favor of
the last good parameter set rather than accepted.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd
from arch import arch_model

from spx_egarch_gex.models.egarch import RETURN_SCALE

logger = logging.getLogger(__name__)

# Plausible one-day-ahead SPX annualized vol forecast range. Calibrated
# empirically: on this same walk-forward, the 2008 GFC peak forecast is
# ~76% and the Mar-2020 COVID peak is ~103% (both legitimate, verified
# against the historical record), while VIX has never closed below ~9%
# (2017-11-03) in its full history. [3%, 150%] sits comfortably outside
# both the realistic floor and the worst legitimate crisis peak observed,
# while still catching degenerate fits -- an earlier, looser [0.5%, 250%]
# band let through both near-zero-vol and >150-246% "forecasts" on ordinary
# trading days in the placid 1993-1995 window, all traced to the same
# optimizer-instability issue as the beta-boundary case below.
MIN_ANNUALIZED_VOL = 0.03
MAX_ANNUALIZED_VOL = 1.5
MAX_ABS_BETA = 0.999  # EGARCH stationarity requires |beta| < 1


def _annualized_vol(var_pct2: float) -> float:
    return (var_pct2**0.5) / RETURN_SCALE * (252**0.5)


def _params_sane(params: pd.Series) -> bool:
    beta = params.get("beta[1]")
    if beta is not None and abs(beta) >= MAX_ABS_BETA:
        return False
    return True


def _forecast_sane(var_pct2: float) -> bool:
    if not np.isfinite(var_pct2) or var_pct2 <= 0:
        return False
    vol = _annualized_vol(var_pct2)
    return MIN_ANNUALIZED_VOL <= vol <= MAX_ANNUALIZED_VOL


@dataclass
class WalkForwardResult:
    window_type: str
    window_size: int | None
    refit_frequency: int
    dist: str
    cond_vol: pd.Series  # one-step-ahead forecast, fractional (not percent) return-scale
    std_resid: pd.Series  # realized_return_t / cond_vol_t
    n_refits: int  # accepted (sane) refits
    n_refits_rejected: int  # refit attempts that failed the sanity check
    n_nonfinite: int  # forecasts dropped: no sane params available yet, or fallback also failed


def walk_forward_egarch(
    returns: pd.Series,
    dist: str = "t",
    window_type: str = "expanding",
    window_size: int | None = None,
    refit_frequency: int = 1,
    min_obs: int = 500,
) -> WalkForwardResult:
    if window_type not in ("expanding", "rolling"):
        raise ValueError("window_type must be 'expanding' or 'rolling'")
    if window_type == "rolling" and not window_size:
        raise ValueError("rolling window requires window_size")

    r = (returns.dropna() * RETURN_SCALE).astype(float)
    dates = r.index
    n = len(r)

    forecasts = np.full(n, np.nan)
    params = None
    n_refits = 0
    n_refits_rejected = 0

    for t in range(min_obs, n):
        # Training window: all data strictly before t (i.e. through t-1).
        lo = 0 if window_type == "expanding" else max(0, t - window_size)
        train = r.iloc[lo:t]

        need_refit = params is None or (t - min_obs) % refit_frequency == 0
        am = arch_model(train, mean="Constant", vol="EGARCH", p=1, o=1, q=1, dist=dist)

        var_pct2 = np.nan
        if need_refit:
            res = am.fit(disp="off", show_warning=False)
            candidate_params = res.params
            candidate_fc = res.forecast(horizon=1, reindex=False)
            candidate_var = candidate_fc.variance.iloc[-1, 0]

            if _params_sane(candidate_params) and _forecast_sane(candidate_var):
                params = candidate_params
                var_pct2 = candidate_var
                n_refits += 1
            else:
                n_refits_rejected += 1
                if params is not None:
                    fixed = am.fix(params)
                    fc = fixed.forecast(horizon=1, reindex=False)
                    var_pct2 = fc.variance.iloc[-1, 0]
                # else: no prior good params yet -> stays nan
        else:
            fixed = am.fix(params)
            fc = fixed.forecast(horizon=1, reindex=False)
            var_pct2 = fc.variance.iloc[-1, 0]

        if _forecast_sane(var_pct2):
            forecasts[t] = np.sqrt(var_pct2) / RETURN_SCALE
        # else leave as NaN (either no params yet, or fallback params also
        # produced an implausible forecast on the new data -- both rare)

    cond_vol = pd.Series(forecasts, index=dates, name="cond_vol_forecast")
    realized = r / RETURN_SCALE  # fractional log returns
    std_resid = (realized / cond_vol).rename("std_resid")
    std_resid = std_resid.replace([np.inf, -np.inf], np.nan)

    n_attempted = n - min_obs
    n_nonfinite = int(cond_vol.iloc[min_obs:].isna().sum())
    if n_refits_rejected or n_nonfinite:
        logger.warning(
            "window_type=%s: %d/%d refits rejected as insane, %d/%d forecasts left NaN",
            window_type, n_refits_rejected, n_refits + n_refits_rejected, n_nonfinite, n_attempted,
        )

    return WalkForwardResult(
        window_type=window_type,
        window_size=window_size,
        refit_frequency=refit_frequency,
        dist=dist,
        cond_vol=cond_vol.dropna(),
        std_resid=std_resid.dropna(),
        n_refits=n_refits,
        n_refits_rejected=n_refits_rejected,
        n_nonfinite=n_nonfinite,
    )


def forecast_eval(cond_vol: pd.Series, returns: pd.Series) -> dict:
    """QLIKE and MSE of variance forecasts against next-day squared return
    (the standard noisy-but-unbiased realized-variance proxy for daily
    one-step-ahead evaluation when no intraday RV series is available)."""
    idx = cond_vol.index.intersection(returns.index)
    var_fcst = (cond_vol.loc[idx]) ** 2
    var_real = (returns.loc[idx]) ** 2
    var_real = var_real.replace(0, np.nan)
    valid = var_fcst.notna() & var_real.notna() & (var_fcst > 0)
    var_fcst, var_real = var_fcst[valid], var_real[valid]

    qlike = float((np.log(var_fcst) + var_real / var_fcst).mean())
    mse = float(((var_fcst - var_real) ** 2).mean())
    return {"qlike": qlike, "mse": mse, "n": int(valid.sum())}
