"""Return-series performance metrics."""

from __future__ import annotations

import numpy as np
import pandas as pd

ANNUALIZATION = 252


def annualized_return(returns: pd.Series) -> float:
    return float(returns.mean() * ANNUALIZATION)


def annualized_vol(returns: pd.Series) -> float:
    return float(returns.std() * np.sqrt(ANNUALIZATION))


def sharpe(returns: pd.Series) -> float:
    vol = annualized_vol(returns)
    return float(annualized_return(returns) / vol) if vol > 0 else float("nan")


def max_drawdown(returns: pd.Series) -> float:
    wealth = (1 + returns.fillna(0)).cumprod()
    peak = wealth.cummax()
    dd = wealth / peak - 1
    return float(dd.min())


def summary(returns: pd.Series) -> dict:
    return {
        "n": int(returns.notna().sum()),
        "ann_return": annualized_return(returns),
        "ann_vol": annualized_vol(returns),
        "sharpe": sharpe(returns),
        "max_drawdown": max_drawdown(returns),
    }
