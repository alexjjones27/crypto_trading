"""Unit tests for the Hyperliquid funding-arb backtest, on synthetic data.

No network calls: every test builds its own funding-record frames and
exercises the fee/breakeven, signal, backtest, rotation, and diagnostic
functions in isolation.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from hyperliquid_funding_arb import (
    CostAssumptions,
    FeeSchedule,
    StrategyConfig,
    HOURS_PER_YEAR,
    _records_to_frame,
    add_annualized_rate,
    breakeven_annualized_rate,
    breakeven_hourly_rate,
    fixed_notional_sizer,
    flag_illiquidity_periods,
    generate_positions_and_backtest,
    run_rotation_backtest,
    run_single_asset_backtest,
)


def make_df(coin: str, start_ms: int, step_ms: int, rates: list[float]) -> pd.DataFrame:
    records = [
        {"coin": coin, "fundingRate": r, "premium": 0.0, "time": start_ms + i * step_ms}
        for i, r in enumerate(rates)
    ]
    return _records_to_frame(records)


HOUR_MS = 3_600_000
DAY_MS = 24 * HOUR_MS


# ---------------------------------------------------------------------------
# Fees / breakeven
# ---------------------------------------------------------------------------

def test_round_trip_cost_matches_hand_calc():
    fees = FeeSchedule()
    maker = CostAssumptions(fees=fees, slippage_bps_per_leg=2.0, fill_type="maker")
    taker = CostAssumptions(fees=fees, slippage_bps_per_leg=2.0, fill_type="taker")

    # one-way = spot fee + perp fee + 2 * slippage; round trip = 2x that.
    assert maker.one_way_cost_bps() == pytest.approx(4.0 + 1.5 + 2 * 2.0)
    assert maker.round_trip_cost_bps() == pytest.approx(2 * (4.0 + 1.5 + 4.0))
    assert taker.one_way_cost_bps() == pytest.approx(7.0 + 4.5 + 2 * 2.0)
    assert taker.round_trip_cost_bps() == pytest.approx(2 * (7.0 + 4.5 + 4.0))
    assert taker.round_trip_cost_bps() > maker.round_trip_cost_bps()


def test_breakeven_scales_inversely_with_horizon():
    costs = CostAssumptions()
    be_24h = breakeven_hourly_rate(costs, 24.0)
    be_48h = breakeven_hourly_rate(costs, 48.0)
    assert be_24h == pytest.approx(2 * be_48h)
    assert breakeven_annualized_rate(costs, 24.0) == pytest.approx(be_24h * HOURS_PER_YEAR)


# ---------------------------------------------------------------------------
# Annualization across the 8h -> 1h cadence switch
# ---------------------------------------------------------------------------

def test_annualized_rate_is_cadence_invariant():
    """A funding rate representing the same underlying hourly rate should
    annualize to (approximately) the same figure whether it was recorded on
    an 8-hourly cadence (rate = 8*r) or an hourly cadence (rate = r)."""
    hourly_r = 0.0001
    eight_h_records = [
        {"coin": "BTC", "fundingRate": hourly_r * 8, "premium": 0.0, "time": i * 8 * HOUR_MS}
        for i in range(5)
    ]
    df8 = _records_to_frame(eight_h_records)
    df8 = add_annualized_rate(df8)

    start = 100 * 8 * HOUR_MS
    one_h_records = [
        {"coin": "BTC", "fundingRate": hourly_r, "premium": 0.0, "time": start + i * HOUR_MS}
        for i in range(5)
    ]
    df1 = _records_to_frame(one_h_records)
    df1 = add_annualized_rate(df1)

    expected = hourly_r * HOURS_PER_YEAR
    assert df8["annualized_rate"].iloc[-1] == pytest.approx(expected, rel=1e-9)
    assert df1["annualized_rate"].iloc[-1] == pytest.approx(expected, rel=1e-9)


# ---------------------------------------------------------------------------
# Signal generation: entry/exit + no lookahead
# ---------------------------------------------------------------------------

def _flat_rate_df(n: int, rate: float, coin="BTC") -> pd.DataFrame:
    return make_df(coin, 0, HOUR_MS, [rate] * n)


def test_no_position_when_below_entry_threshold():
    costs = CostAssumptions()
    cfg = StrategyConfig(buffer_multiplier=2.0, breakeven_horizon_hours=24.0)
    be = breakeven_hourly_rate(costs, cfg.breakeven_horizon_hours)
    df = _flat_rate_df(50, rate=be * 0.5)  # well under breakeven, never mind the buffer
    res = run_single_asset_backtest(df, costs, cfg)
    assert (res["df"]["side"] == 0).all()
    assert len(res["trades"]) == 0


def test_entry_when_above_buffered_threshold_then_exit_below_breakeven():
    costs = CostAssumptions()
    cfg = StrategyConfig(buffer_multiplier=2.0, breakeven_horizon_hours=24.0)
    be_hourly = breakeven_hourly_rate(costs, cfg.breakeven_horizon_hours)
    entry_hourly = 3 * be_hourly  # comfortably above 2x breakeven buffer

    n = 30
    rates = [entry_hourly] * n
    rates[10] = be_hourly * 0.1  # funding collapses -> should trigger exit
    for i in range(11, n):
        rates[i] = be_hourly * 0.1
    df = make_df("BTC", 0, HOUR_MS, rates)

    res = run_single_asset_backtest(df, costs, cfg)
    out = res["df"]
    trades = res["trades"]

    assert out["is_entry"].iloc[0]  # first bar already clears the buffered threshold
    assert len(trades) == 1
    assert trades.iloc[0]["exit_reason"] == "below_breakeven"
    # exit should fire at index 10, once the rate has actually dropped
    assert out.index[out["is_exit"]].tolist() == [10]

    # No lookahead: pnl at row i must depend only on side decided at row i-1.
    held = out["held_side"].to_numpy()
    side = out["side"].to_numpy()
    assert (held[1:] == side[:-1]).all()
    assert held[0] == 0  # nothing was held into the very first row


def test_max_holding_period_forces_exit_when_rate_never_drops():
    costs = CostAssumptions()
    cfg = StrategyConfig(buffer_multiplier=2.0, breakeven_horizon_hours=24.0, max_holding_hours=5.0)
    be_hourly = breakeven_hourly_rate(costs, cfg.breakeven_horizon_hours)
    df = _flat_rate_df(30, rate=5 * be_hourly)  # always well above breakeven, never exits naturally

    res = run_single_asset_backtest(df, costs, cfg)
    trades = res["trades"]
    assert len(trades) >= 2  # forced to repeatedly exit and re-enter every ~5h
    assert (trades["exit_reason"].iloc[:-1] == "max_holding").all()
    for h in trades["hours_held"].iloc[:-1]:
        assert h == pytest.approx(5.0, abs=0.01)


def test_sign_flip_closes_and_reopens_opposite_side():
    costs = CostAssumptions()
    cfg = StrategyConfig(buffer_multiplier=2.0, breakeven_horizon_hours=24.0)
    be_hourly = breakeven_hourly_rate(costs, cfg.breakeven_horizon_hours)
    strong = 4 * be_hourly
    rates = [strong] * 10 + [-strong] * 10
    df = make_df("BTC", 0, HOUR_MS, rates)

    res = run_single_asset_backtest(df, costs, cfg)
    trades = res["trades"]
    assert len(trades) == 2
    assert trades.iloc[0]["side"] == 1
    assert trades.iloc[0]["exit_reason"] == "flip"
    assert trades.iloc[1]["side"] == -1


def test_fees_charged_on_entry_and_exit_only():
    costs = CostAssumptions(fill_type="maker", slippage_bps_per_leg=2.0)
    cfg = StrategyConfig(buffer_multiplier=2.0, breakeven_horizon_hours=24.0, notional=10_000.0)
    be_hourly = breakeven_hourly_rate(costs, cfg.breakeven_horizon_hours)
    rates = [3 * be_hourly] * 5 + [0.0] * 5
    df = make_df("BTC", 0, HOUR_MS, rates)

    res = run_single_asset_backtest(df, costs, cfg, sizer=fixed_notional_sizer(cfg.notional))
    out = res["df"]

    one_way_frac = costs.one_way_cost_bps() / 1e4
    expected_entry_fee = cfg.notional * one_way_frac
    entry_rows = out[out["is_entry"]]
    exit_rows = out[out["is_exit"]]
    assert len(entry_rows) == 1 and len(exit_rows) == 1
    assert entry_rows["fees_paid"].iloc[0] == pytest.approx(expected_entry_fee)
    assert exit_rows["fees_paid"].iloc[0] == pytest.approx(expected_entry_fee)
    non_trade_rows = out[~(out["is_entry"] | out["is_exit"])]
    assert (non_trade_rows["fees_paid"] == 0).all()


# ---------------------------------------------------------------------------
# Rotation
# ---------------------------------------------------------------------------

def test_rotation_picks_widest_margin_asset():
    costs = CostAssumptions()
    cfg = StrategyConfig(buffer_multiplier=2.0, breakeven_horizon_hours=24.0)
    be_hourly = breakeven_hourly_rate(costs, cfg.breakeven_horizon_hours)

    n = 20
    btc = make_df("BTC", 0, HOUR_MS, [3 * be_hourly] * n)
    eth = make_df("ETH", 0, HOUR_MS, [6 * be_hourly] * n)  # clears breakeven by a wider margin
    sol = make_df("SOL", 0, HOUR_MS, [0.1 * be_hourly] * n)  # never qualifies

    res = run_rotation_backtest({"BTC": btc, "ETH": eth, "SOL": sol}, costs, cfg)
    trades = res["trades"]
    assert len(trades) >= 1
    assert trades.iloc[0]["coin"] == "ETH"
    assert (trades["coin"] != "SOL").all()


def test_rotation_pnl_uses_correct_coins_funding_rate():
    costs = CostAssumptions()
    cfg = StrategyConfig(buffer_multiplier=2.0, breakeven_horizon_hours=24.0, notional=1_000.0)
    be_hourly = breakeven_hourly_rate(costs, cfg.breakeven_horizon_hours)

    n = 10
    btc = make_df("BTC", 0, HOUR_MS, [5 * be_hourly] * n)
    eth = make_df("ETH", 0, HOUR_MS, [0.0] * n)
    sol = make_df("SOL", 0, HOUR_MS, [0.0] * n)

    res = run_rotation_backtest({"BTC": btc, "ETH": eth, "SOL": sol}, costs, cfg)
    out = res["df"]
    # Once holding BTC, funding pnl on later rows should equal BTC's raw
    # fundingRate * notional (side=+1), not ETH/SOL's zero rate.
    held_rows = out[out["held_side"] != 0]
    assert len(held_rows) > 0
    expected = cfg.notional * (5 * be_hourly)
    assert held_rows["funding_pnl"].iloc[-1] == pytest.approx(expected, rel=1e-6)


# ---------------------------------------------------------------------------
# Illiquidity flag
# ---------------------------------------------------------------------------

def test_flags_persistent_one_directional_run():
    n_hours = 24 * 20  # 20 days, all positive -- should be flagged (>14d default)
    df = _flat_rate_df(n_hours, rate=0.0005)
    flags = flag_illiquidity_periods(df, min_run_hours=24 * 14)
    assert len(flags) == 1
    assert flags.iloc[0]["direction"] == "positive"
    assert flags.iloc[0]["run_hours"] == pytest.approx((n_hours - 1) * 1.0, abs=1.0)


def test_does_not_flag_short_runs():
    n_hours = 24 * 5  # only 5 days
    df = _flat_rate_df(n_hours, rate=0.0005)
    flags = flag_illiquidity_periods(df, min_run_hours=24 * 14)
    assert len(flags) == 0
