"""Inference tools that stay valid under serial correlation / vol clustering,
which plain t-tests and i.i.d. bootstraps assume away.

- `newey_west_tstat`: HAC-corrected t-stat for whether a return series has
  nonzero mean (used for full-strategy significance in checkpoint 5, but
  built here since it's a generic time-series-mean tool).
- `circular_shift_permutation_test`: tests whether a (label, value) time
  series association is stronger than chance, by comparing the observed
  statistic to a null built from circularly shifting the label series
  relative to the value series. Preserves each series' own serial
  correlation / persistence (it's a rotation, not a reshuffle) while
  destroying genuine alignment between them -- appropriate for both the
  regime-vs-vol test (checkpoint 3) and later strategy-return tests
  (checkpoint 5), which have exactly this "is a persistent, autocorrelated
  label associated with a persistent, autocorrelated series" shape.
"""

from __future__ import annotations

from typing import Callable

import numpy as np
import pandas as pd
import statsmodels.api as sm


def newey_west_tstat(returns: pd.Series, lags: int | None = None) -> dict:
    """HAC (Newey-West) t-stat for H0: mean(returns) == 0.

    `lags` defaults to the common floor(4*(n/100)^(2/9)) rule of thumb if
    not given.
    """
    r = returns.dropna()
    n = len(r)
    if lags is None:
        lags = int(np.floor(4 * (n / 100) ** (2 / 9)))
    X = np.ones((n, 1))
    model = sm.OLS(r.values, X).fit(cov_type="HAC", cov_kwds={"maxlags": lags})
    return {
        "mean": float(model.params[0]),
        "se": float(model.bse[0]),
        "tstat": float(model.tvalues[0]),
        "pvalue": float(model.pvalues[0]),
        "n": n,
        "lags": lags,
    }


def circular_shift_permutation_test(
    labels: pd.Series,
    values: pd.Series,
    statistic_fn: Callable[[pd.Series, pd.Series], float],
    n_perm: int = 2000,
    random_state: int | None = 0,
) -> dict:
    aligned = pd.concat([labels.rename("label"), values.rename("value")], axis=1).dropna()
    n = len(aligned)
    observed = statistic_fn(aligned["label"], aligned["value"])

    rng = np.random.default_rng(random_state)
    label_arr = aligned["label"].to_numpy()
    value_ser = aligned["value"]
    null_stats = np.empty(n_perm)
    for i in range(n_perm):
        shift = rng.integers(1, n)
        shifted_labels = pd.Series(np.roll(label_arr, shift), index=aligned.index)
        null_stats[i] = statistic_fn(shifted_labels, value_ser)

    p_value = (np.sum(np.abs(null_stats) >= abs(observed)) + 1) / (n_perm + 1)
    return {
        "observed": float(observed),
        "null_mean": float(np.nanmean(null_stats)),
        "null_std": float(np.nanstd(null_stats)),
        "p_value": float(p_value),
        "n_perm": n_perm,
        "n_obs": n,
    }
