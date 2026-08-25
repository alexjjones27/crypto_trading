"""Build the daily inputs the strategy engine needs: regime label (lagged for
real-time availability), EGARCH vol forecast, mean-reversion z-score, and
vol-breakout indicator. All walk-forward safe: every column at row t is
computable using only information known before t's trading decision.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from spx_egarch_gex import config
from spx_egarch_gex.regime.classifier import classify_regime_sign, lag_for_trading


def build_signal_frame() -> pd.DataFrame:
    panel = pd.read_csv(config.PROCESSED_DIR / "panel.csv", index_col="date", parse_dates=["date"])
    egarch = pd.read_csv(
        config.PROCESSED_DIR / "egarch_forecasts_expanding.csv", index_col=0, parse_dates=True
    )

    df = pd.DataFrame(index=panel.index)
    df["ret"] = panel["spx_log_ret"]
    df["gex"] = panel["gex"]

    regime_raw = classify_regime_sign(df["gex"])
    df["regime"] = lag_for_trading(regime_raw, lag=config.REGIME_LAG)

    # cond_vol_forecast[t]: one-step-ahead forecast for day t, made using
    # data through t-1 (see checkpoint 2) -- i.e. legitimately known before
    # t's return realizes. Daily (not annualized) fractional units.
    df["vol_fcst"] = egarch["cond_vol_expanding"]
    df["vol_fcst_ann"] = df["vol_fcst"] * np.sqrt(252)

    # Mean-reversion z-score: trailing n-day cumulative log return,
    # standardized by that day's forecast vol scaled to the same horizon.
    # This uses ret[t] (realized only at t's close), so -- unlike regime and
    # vol_fcst above, which are already dated to the day they inform --
    # it's only knowable at t's close and must be shifted to inform t+1's
    # decision. Same for the breakout indicator below. After the shift,
    # EVERY column in this frame consistently means "known before the
    # trading day in its own row," so the strategy engine can read row t
    # directly as the information set for deciding day t's position without
    # any further lagging.
    n = config.MR_LOOKBACK_DAYS
    trailing_ret = df["ret"].rolling(n).sum()
    mr_z_at_close = trailing_ret / (df["vol_fcst"] * np.sqrt(n))
    df["mr_z"] = mr_z_at_close.shift(1)

    # Vol-breakout indicator: that close's realized return relative to the
    # vol that had been forecast for it -- "how many forecast-sigmas was
    # the move," shifted the same way.
    breakout_at_close = df["ret"] / df["vol_fcst"]
    df["breakout_sigma"] = breakout_at_close.shift(1)

    return df
