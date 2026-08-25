"""Dealer gamma-exposure regime classifier.

Definition (given, not derived): positive aggregate dealer GEX means
dealers are net long gamma, so their hedging flow is counter to price
moves (buy dips, sell rallies) -> suppressed realized vol, mean reversion
favored. Negative GEX means dealers are net short gamma, hedging WITH
price direction (sell into declines, buy into rallies) -> amplified
realized vol, trend/momentum favored.

Classifier: sign(GEX_t) against a zero threshold. This is the natural,
non-arbitrary threshold for this signal: the SIGN of aggregate dealer
gamma exposure is what determines the DIRECTION of their hedging flow
(with price vs against it) -- it is a statement about the sign of a sum
of per-strike dealer gamma positions, not about its dollar magnitude. No
lookback/smoothing is applied in the primary classifier: GEX is already a
level (current aggregate positioning as of that day's option open
interest), not a flow that needs averaging. A magnitude-aware variant
(tercile thresholds, excluding the near-zero "noisy" middle band) is
provided separately as a robustness check (see checkpoint 6 sensitivity
analysis), not as the primary definition.

CRITICAL: this module only labels GEX_t by the date it describes. It does
NOT decide which trading day that label may legitimately be used on --
that is a separate question of real-time availability / publish lag,
handled by `lag_for_trading` below and documented in
results/checkpoint3_regime_standalone.txt.
"""

from __future__ import annotations

import pandas as pd


def classify_regime_sign(gex: pd.Series, threshold: float = 0.0) -> pd.Series:
    """Label each day 'positive' or 'negative' by raw GEX vs `threshold` (default 0)."""
    label = pd.Series(index=gex.index, dtype=object)
    label[gex > threshold] = "positive"
    label[gex <= threshold] = "negative"
    label[gex.isna()] = None  # plain None, not pd.NA: keeps `label[i] == "positive"` a clean bool
    return label.rename("regime")


def classify_regime_tercile(gex: pd.Series, lookback: int | None = None) -> pd.Series:
    """Robustness variant: label by trailing tercile of GEX level rather than a
    literal zero threshold, excluding the middle ("neutral") tercile.

    If `lookback` is given, terciles are computed on a trailing rolling window
    (walk-forward safe: window ends at t, so the label for day t only uses
    GEX through day t). If None, terciles are computed on the full sample
    (NOT walk-forward safe -- for descriptive/robustness use only, not for
    anything backtested for P&L).
    """
    if lookback is None:
        q1, q2 = gex.quantile([1 / 3, 2 / 3])
        label = pd.Series(index=gex.index, dtype=object)
        label[gex <= q1] = "negative"
        label[gex >= q2] = "positive"
        label[(gex > q1) & (gex < q2)] = "neutral"
        label[gex.isna()] = pd.NA
        return label.rename("regime_tercile")

    q1 = gex.rolling(lookback, min_periods=lookback).quantile(1 / 3)
    q2 = gex.rolling(lookback, min_periods=lookback).quantile(2 / 3)
    label = pd.Series(index=gex.index, dtype=object)
    label[gex <= q1] = "negative"
    label[gex >= q2] = "positive"
    label[(gex > q1) & (gex < q2)] = "neutral"
    label[gex.isna() | q1.isna()] = pd.NA
    return label.rename("regime_tercile")


def lag_for_trading(regime: pd.Series, lag: int = 1) -> pd.Series:
    """Shift a regime label series forward by `lag` trading days so that the
    label used to inform the decision made *for* day t was actually knowable
    *before* day t's trading. E.g. lag=1: the regime driving day t's trade is
    the label computed from GEX_{t-1} (known at t-1's close).
    """
    return regime.shift(lag)
