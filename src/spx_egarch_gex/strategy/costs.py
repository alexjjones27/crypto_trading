"""Transaction cost and financing cost model.

Assumes execution via ES futures (deep liquidity, not the non-tradeable
SPX index itself). Two components, both charged as a daily drag on the
strategy's return series:

- Turnover cost: TRANSACTION_COST_BPS per unit of *notional traded*, i.e.
  |position_t - position_{t-1}| -- covers commission, half-spread, and
  typical slippage for ES-sized clips.
- Financing cost: vol-targeting can lever above 1x notional; the excess
  is assumed borrowed at FINANCING_SPREAD_ANNUAL over the risk-free rate
  (this repo doesn't model the risk-free rate itself, so this is a spread
  ON TOP of whatever risk-free return a real cash-secured account would
  earn -- i.e. it's the incremental cost of leverage, not total financing).
"""

from __future__ import annotations

import pandas as pd

from spx_egarch_gex import config


def apply_costs(position: pd.Series, returns: pd.Series) -> pd.DataFrame:
    pos = position.fillna(0.0)
    ret = returns.reindex(pos.index)

    turnover = pos.diff().abs().fillna(pos.abs())  # first day: turnover from 0
    turnover_cost = turnover * (config.TRANSACTION_COST_BPS / 10_000)

    excess_leverage = (pos.abs() - 1.0).clip(lower=0.0)
    financing_cost = excess_leverage * (config.FINANCING_SPREAD_ANNUAL / 252)

    # `position[t]` is already the engine's day-t target, computed from
    # information known before t's trading (see engine.py) and meant to
    # earn ret[t] directly -- no further shift here. Costs are charged on
    # day t as well, the same day the position moves from position[t-1] to
    # position[t] and the new exposure starts earning returns.
    gross_ret = pos * ret
    net_ret = gross_ret - turnover_cost - financing_cost

    return pd.DataFrame({
        "position": pos,
        "turnover": turnover,
        "turnover_cost": turnover_cost,
        "financing_cost": financing_cost,
        "gross_ret": gross_ret,
        "net_ret": net_ret,
    })
