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
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from arch import arch_model

from spx_egarch_gex.models.egarch import RETURN_SCALE


@dataclass
class WalkForwardResult:
    window_type: str
    window_size: int | None
    refit_frequency: int
    dist: str
    cond_vol: pd.Series  # one-step-ahead forecast, fractional (not percent) return-scale
    std_resid: pd.Series  # realized_return_t / cond_vol_t
    n_refits: int


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

    for t in range(min_obs, n):
        # Training window: all data strictly before t (i.e. through t-1).
        lo = 0 if window_type == "expanding" else max(0, t - window_size)
        train = r.iloc[lo:t]

        need_refit = params is None or (t - min_obs) % refit_frequency == 0
        am = arch_model(train, mean="Constant", vol="EGARCH", p=1, o=1, q=1, dist=dist)

        if need_refit:
            res = am.fit(disp="off", show_warning=False)
            params = res.params
            n_refits += 1
            fc = res.forecast(horizon=1, reindex=False)
        else:
            fixed = am.fix(params)
            fc = fixed.forecast(horizon=1, reindex=False)

        # variance forecast is in (returns*100)^2 units -> back to fractional
        var_pct2 = fc.variance.iloc[-1, 0]
        forecasts[t] = np.sqrt(var_pct2) / RETURN_SCALE

    cond_vol = pd.Series(forecasts, index=dates, name="cond_vol_forecast")
    realized = r / RETURN_SCALE  # fractional log returns
    std_resid = (realized / cond_vol).rename("std_resid")

    return WalkForwardResult(
        window_type=window_type,
        window_size=window_size,
        refit_frequency=refit_frequency,
        dist=dist,
        cond_vol=cond_vol.dropna(),
        std_resid=std_resid.dropna(),
        n_refits=n_refits,
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
