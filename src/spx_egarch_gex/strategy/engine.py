"""Position-generation state machine.

Reads the signal frame from `signals.build_signal_frame` (every column
already dated to the day it's safe to use for THAT day's decision -- see
that module's docstring) and produces a daily target position series
(fraction of vol-targeted notional, signed by direction) plus a trade log.

Two mutually-exclusive sub-strategies, gated by regime so at most one is
ever eligible to open a new trade on a given day; an open trade is closed
immediately if its regime is no longer active (see each block below).

Mean-reversion (regime == positive):
  Entry:  |mr_z| > MR_ENTRY_Z -> fade the move (short if z>0, long if z<0)
  Exit:   regime flips away from positive, OR |mr_z| reverts inside
          MR_EXIT_Z, OR MR_MAX_HOLD_DAYS elapsed.

Vol-breakout (regime == negative):
  Entry:  |breakout_sigma| > BRK_ENTRY_SIGMA -> FOLLOW the move's direction
          (momentum, back to checkpoint 4's original framing). checkpoint 4b
          flipped this to contrarian based on an A/B test that, per the
          leakage check, was run on the full 2011-2026 sample including the
          entire planned holdout -- contaminated. Re-run as a proper nested
          selection (fit on in-sample 2011-2017, decide on validation
          2018-2020 only, holdout never read) reversed the conclusion:
          momentum beats contrarian on BOTH in-sample (mean trade return
          +0.27% vs -0.55%) and validation (+0.09% vs -0.61%). The
          "contrarian wins" result was an artifact of whatever's in
          2021-2026, not a finding that survives leak-free evaluation.
  Exit:   regime flips away from negative, OR a vol-scaled trailing stop
          (BRK_TRAILING_STOP_SIGMA daily-vol-units of retracement from the
          trade's best point so far) triggers, OR BRK_MAX_HOLD_DAYS elapsed.
          This remains a payoff-convexity design (let winners run, cut
          losers on a stop) rather than a hold-to-target bet -- checkpoint
          3's standalone regime test still didn't show a strong directional
          persistence edge on its own, so the trailing stop is doing real
          work here, not just tidying up a already-strong signal.

Sizing (both): vol-targeted, TARGET_ANNUALIZED_VOL / vol_fcst_ann_t, capped
at MAX_LEVERAGE, re-sized every day a position is held (not fixed at
entry) since it's cheap to do and keeps realized vol closer to target
throughout the trade's life.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from spx_egarch_gex import config


@dataclass
class Trade:
    strategy: str  # 'mean_reversion' | 'vol_breakout'
    direction: int  # +1 / -1
    entry_date: pd.Timestamp
    exit_date: pd.Timestamp
    days_held: int
    cum_return: float  # sum of raw log returns while held (unlevered)
    exit_reason: str


def _vol_target_size(vol_fcst_ann: float) -> float:
    if not np.isfinite(vol_fcst_ann) or vol_fcst_ann <= 0:
        return 0.0
    return min(config.TARGET_ANNUALIZED_VOL / vol_fcst_ann, config.MAX_LEVERAGE)


def generate_positions(df: pd.DataFrame) -> tuple[pd.Series, list[Trade]]:
    positions = np.zeros(len(df))
    state = "flat"
    direction = 0
    days_held = 0
    cum_ret_since_entry = 0.0
    peak_favorable = 0.0
    entry_date = None
    entry_strategy = None
    trades: list[Trade] = []

    dates = df.index
    regime = df["regime"].to_numpy()
    vol_fcst_ann = df["vol_fcst_ann"].to_numpy()
    mr_z = df["mr_z"].to_numpy()
    breakout_sigma = df["breakout_sigma"].to_numpy()
    ret = df["ret"].to_numpy()
    vol_fcst = df["vol_fcst"].to_numpy()

    for i in range(len(df)):
        # --- process exits for an already-open trade, using info known before today ---
        if state in ("long_mr", "short_mr"):
            days_held += 1
            exit_reason = None
            if regime[i] != "positive":
                exit_reason = "regime_flip"
            elif np.isfinite(mr_z[i]) and abs(mr_z[i]) < config.MR_EXIT_Z:
                exit_reason = "reverted"
            elif days_held >= config.MR_MAX_HOLD_DAYS:
                exit_reason = "max_hold"
            if exit_reason:
                trades.append(Trade("mean_reversion", direction, entry_date, dates[i], days_held,
                                     cum_ret_since_entry, exit_reason))
                state, direction, days_held, cum_ret_since_entry, peak_favorable = "flat", 0, 0, 0.0, 0.0

        elif state in ("long_brk", "short_brk"):
            days_held += 1
            exit_reason = None
            favorable = direction * cum_ret_since_entry
            stop_dist = config.BRK_TRAILING_STOP_SIGMA * vol_fcst[i] if np.isfinite(vol_fcst[i]) else np.inf
            if regime[i] != "negative":
                exit_reason = "regime_flip"
            elif (peak_favorable - favorable) > stop_dist:
                exit_reason = "trailing_stop"
            elif days_held >= config.BRK_MAX_HOLD_DAYS:
                exit_reason = "max_hold"
            if exit_reason:
                trades.append(Trade("vol_breakout", direction, entry_date, dates[i], days_held,
                                     cum_ret_since_entry, exit_reason))
                state, direction, days_held, cum_ret_since_entry, peak_favorable = "flat", 0, 0, 0.0, 0.0

        # --- process entries (only if currently flat) ---
        if state == "flat":
            if regime[i] == "positive" and np.isfinite(mr_z[i]):
                if mr_z[i] > config.MR_ENTRY_Z:
                    state, direction = "short_mr", -1
                elif mr_z[i] < -config.MR_ENTRY_Z:
                    state, direction = "long_mr", 1
                if state != "flat":
                    days_held, cum_ret_since_entry, peak_favorable = 0, 0.0, 0.0
                    entry_date, entry_strategy = dates[i], "mean_reversion"
            elif regime[i] == "negative" and np.isfinite(breakout_sigma[i]):
                # momentum: follow the move (see module docstring -- reverted
                # from checkpoint 4b's contrarian flip after the leakage check)
                if breakout_sigma[i] > config.BRK_ENTRY_SIGMA:
                    state, direction = "long_brk", 1
                elif breakout_sigma[i] < -config.BRK_ENTRY_SIGMA:
                    state, direction = "short_brk", -1
                if state != "flat":
                    days_held, cum_ret_since_entry, peak_favorable = 0, 0.0, 0.0
                    entry_date, entry_strategy = dates[i], "vol_breakout"

        # --- size today's position ---
        size = _vol_target_size(vol_fcst_ann[i]) if state != "flat" else 0.0
        positions[i] = direction * size

        # --- observe today's return, roll it into the open trade's running P&L for tomorrow's checks ---
        if state != "flat" and np.isfinite(ret[i]):
            cum_ret_since_entry += ret[i]
            peak_favorable = max(peak_favorable, direction * cum_ret_since_entry)

    position_series = pd.Series(positions, index=df.index, name="position")
    return position_series, trades
