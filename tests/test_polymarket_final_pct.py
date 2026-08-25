"""Unit tests for the Polymarket final-1% backtest, on synthetic data.

No network calls: every test builds its own price series / market dicts
and exercises the signal, fee, backtest, and statistics functions in
isolation.
"""

from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd
import pytest

from polymarket_final_pct import (
    BacktestConfig,
    FillAssumptions,
    GasAssumptions,
    SignalConfig,
    categorize_flip,
    classify_fee_category,
    classify_report_bucket,
    clopper_pearson_interval,
    compute_metrics,
    compute_with_vs_without_flips,
    detect_crossing,
    maker_fee_frac_of_notional,
    resolved_outcome_index,
    simulate_trade,
    taker_fee_frac_of_notional,
    wilson_interval,
)


def price_df(prices: list[float], start_t: int = 1_700_000_000, step: int = 60) -> pd.DataFrame:
    t = [start_t + i * step for i in range(len(prices))]
    return pd.DataFrame({"t": t, "p": prices})


# ---------------------------------------------------------------------------
# Crossing detection / no lookahead
# ---------------------------------------------------------------------------

def test_no_crossing_below_threshold():
    df = price_df([0.5, 0.8, 0.95, 0.97, 0.98])
    assert detect_crossing(df, threshold=0.99, n_consecutive=3) is None


def test_single_noisy_tick_does_not_trigger():
    df = price_df([0.5, 0.6, 0.995, 0.7, 0.8])  # one-off spike, not persistent
    assert detect_crossing(df, threshold=0.99, n_consecutive=3) is None


def test_crossing_requires_n_consecutive_and_uses_actual_price():
    df = price_df([0.5, 0.6, 0.991, 0.993, 0.997, 0.6])
    hit = detect_crossing(df, threshold=0.99, n_consecutive=3)
    assert hit is not None
    # confirmed on the 3rd consecutive qualifying snapshot (index 4), at ITS
    # actual price, not a hypothetical fill at exactly 0.99
    assert hit["entry_idx"] == 4
    assert hit["entry_price"] == pytest.approx(0.997)


def test_crossing_fires_at_earliest_qualifying_run_not_a_later_one():
    df = price_df([0.5, 0.991, 0.992, 0.993, 0.5, 0.994, 0.995, 0.996])
    hit = detect_crossing(df, threshold=0.99, n_consecutive=3)
    assert hit["entry_idx"] == 3  # first run, not the second later run at idx 7


def test_n_consecutive_is_configurable():
    df = price_df([0.995, 0.996])
    assert detect_crossing(df, threshold=0.99, n_consecutive=3) is None
    hit = detect_crossing(df, threshold=0.99, n_consecutive=2)
    assert hit is not None and hit["entry_idx"] == 1


def test_empty_series_returns_none():
    assert detect_crossing(price_df([]), threshold=0.99, n_consecutive=3) is None


# ---------------------------------------------------------------------------
# Fees (confirmed formula: fee = shares * feeRate * p * (1-p); maker == 0)
# ---------------------------------------------------------------------------

def test_maker_fee_is_always_zero():
    assert maker_fee_frac_of_notional(0.99, "crypto") == 0.0
    assert maker_fee_frac_of_notional(0.50, "sports") == 0.0


def test_taker_fee_matches_confirmed_worked_examples():
    # docs' own worked examples: 100 shares @ $0.50 -> crypto $1.75, sports
    # $1.25, politics $1.00. fee_frac_of_notional = feeRate * (1-p); dollar
    # fee = frac * notional = frac * (100 * 0.50).
    for category, expected_dollar_fee in [("crypto", 1.75), ("sports", 1.25), ("politics", 1.00)]:
        frac = taker_fee_frac_of_notional(0.50, category)
        notional = 100 * 0.50
        assert frac * notional == pytest.approx(expected_dollar_fee, abs=1e-9)


def test_taker_fee_shrinks_near_the_extreme():
    frac_mid = taker_fee_frac_of_notional(0.50, "crypto")
    frac_extreme = taker_fee_frac_of_notional(0.99, "crypto")
    assert frac_extreme < frac_mid
    assert frac_extreme == pytest.approx(0.07 * 0.01)


def test_gas_sponsored_vs_non_relayed():
    assert GasAssumptions(relayer_sponsored=True).cost_usd() == 0.0
    g = GasAssumptions(relayer_sponsored=False, non_relayed_cost_usd_per_trade=0.0042)
    assert g.cost_usd() == pytest.approx(0.0042)


# ---------------------------------------------------------------------------
# Category classification
# ---------------------------------------------------------------------------

def test_classify_report_bucket_politics():
    m = {"question": "Will the Democrat nominee win the presidential election?", "slug": "x", "events": []}
    assert classify_report_bucket(m) == "politics"


def test_classify_report_bucket_sports():
    m = {"question": "Lakers vs Celtics: who wins Game 7?", "slug": "x", "events": []}
    assert classify_report_bucket(m) == "sports"


def test_classify_report_bucket_crypto_price():
    m = {"question": "Bitcoin Up or Down - August 25, 8:25AM-8:30AM ET", "slug": "btc-updown", "events": []}
    assert classify_report_bucket(m) == "crypto_price"


def test_classify_fee_category_maps_to_official_taxonomy():
    m = {"question": "Will Bitcoin hit $100k?", "slug": "x", "events": []}
    assert classify_fee_category(m) == "crypto"


# ---------------------------------------------------------------------------
# Resolved outcome parsing (must never feed back into signal generation --
# tested structurally: detect_crossing above takes no market/outcome data)
# ---------------------------------------------------------------------------

def test_resolved_outcome_index_from_outcome_prices():
    assert resolved_outcome_index({"outcomePrices": json.dumps(["1", "0"])}) == 0
    assert resolved_outcome_index({"outcomePrices": json.dumps(["0", "1"])}) == 1


def test_resolved_outcome_index_none_when_ambiguous():
    assert resolved_outcome_index({"outcomePrices": json.dumps(["0", "0"])}) is None
    assert resolved_outcome_index({"outcomePrices": "[]"}) is None


# ---------------------------------------------------------------------------
# Trade simulation: fees, gas, depth cap, payout
# ---------------------------------------------------------------------------

def _market(question="Will Bitcoin hit $100k?", outcome_prices=("0", "1")):
    return {
        "id": "1", "conditionId": "0xabc", "question": question,
        "outcomePrices": json.dumps(list(outcome_prices)),
        "endDate": "2024-01-10T00:00:00Z", "closedTime": "2024-01-10T00:00:00Z",
        "slug": "x", "events": [],
    }


def _crossing(entry_price=0.995, outcome_index=1, entry_time_s=1_704_800_000):
    return {
        "token_id": "tok1", "outcome_index": outcome_index, "outcome_label": "Yes",
        "entry_time_s": entry_time_s, "entry_price": entry_price,
        "data_source": "fine_direct", "days_to_scheduled_end_at_entry": 1.0,
    }


def test_winning_trade_payout_and_pnl():
    cfg = BacktestConfig(signal=SignalConfig(), position_notional=100.0, gas=GasAssumptions(relayer_sponsored=True))
    fill = FillAssumptions(fill_type="maker")
    t = simulate_trade(_crossing(entry_price=0.99, outcome_index=1), _market(), fill, cfg, cap_shares=None)
    assert t["won"] is True
    shares = 100.0 / 0.99
    assert t["shares"] == pytest.approx(shares)
    assert t["payout"] == pytest.approx(shares * 1.0)
    assert t["fee_cost"] == 0.0  # maker
    assert t["pnl_gross"] == pytest.approx(shares - 100.0)
    assert t["pnl_net"] == pytest.approx(t["pnl_gross"])  # no fee, no gas


def test_flipped_trade_loses_full_notional():
    cfg = BacktestConfig(signal=SignalConfig(), position_notional=100.0, gas=GasAssumptions(relayer_sponsored=True))
    fill = FillAssumptions(fill_type="maker")
    # entered on outcome_index=0 but outcome_index=1 resolved -> flip
    t = simulate_trade(_crossing(entry_price=0.99, outcome_index=0), _market(outcome_prices=("0", "1")), fill, cfg, cap_shares=None)
    assert t["won"] is False
    assert t["payout"] == 0.0
    assert t["pnl_net"] == pytest.approx(-t["notional"])


def test_taker_fee_reduces_net_pnl_vs_maker():
    cfg = BacktestConfig(signal=SignalConfig(), position_notional=100.0, gas=GasAssumptions(relayer_sponsored=True))
    maker_t = simulate_trade(_crossing(entry_price=0.99, outcome_index=1), _market(), FillAssumptions("maker"), cfg, cap_shares=None)
    taker_t = simulate_trade(_crossing(entry_price=0.99, outcome_index=1), _market(), FillAssumptions("taker"), cfg, cap_shares=None)
    assert taker_t["fee_cost"] > 0
    assert taker_t["pnl_net"] < maker_t["pnl_net"]


def test_depth_cap_reduces_position_size():
    cfg = BacktestConfig(signal=SignalConfig(), position_notional=100.0, gas=GasAssumptions(relayer_sponsored=True))
    fill = FillAssumptions(fill_type="maker")
    desired_shares = 100.0 / 0.99
    t = simulate_trade(_crossing(entry_price=0.99, outcome_index=1), _market(), fill, cfg, cap_shares=desired_shares / 2)
    assert t["depth_capped"] is True
    assert t["shares"] == pytest.approx(desired_shares / 2)
    assert t["notional"] < 100.0


def test_non_relayed_gas_charged_per_trade():
    cfg = BacktestConfig(
        signal=SignalConfig(), position_notional=100.0,
        gas=GasAssumptions(relayer_sponsored=False, non_relayed_cost_usd_per_trade=0.01),
    )
    fill = FillAssumptions(fill_type="maker")
    t = simulate_trade(_crossing(entry_price=0.99, outcome_index=1), _market(), fill, cfg, cap_shares=None)
    assert t["gas_cost"] == pytest.approx(0.01)
    assert t["pnl_net"] == pytest.approx(t["pnl_gross"] - 0.01)


# ---------------------------------------------------------------------------
# Metrics: annualized return uses actual per-trade holding period
# ---------------------------------------------------------------------------

def _trades_df(rows):
    return pd.DataFrame(rows)


def test_annualized_return_uses_actual_holding_period_not_fixed_assumption():
    # two trades, same $ pnl, different holding periods -> different
    # annualized return (dollar-year-weighted), same total return.
    rows = [
        {"notional": 100.0, "pnl_net": 1.0, "pnl_gross": 1.0, "holding_days": 1.0, "won": True},
        {"notional": 100.0, "pnl_net": 1.0, "pnl_gross": 1.0, "holding_days": 100.0, "won": True},
    ]
    m = compute_metrics(_trades_df(rows))
    assert m["total_return"] == pytest.approx(2.0 / 200.0)
    # short-holding trade contributes much more annualized return per dollar-year
    dollar_years = (100 * 1 / 365.0) + (100 * 100 / 365.0)
    assert m["annualized_return"] == pytest.approx(2.0 / dollar_years)


def test_win_rate_and_flip_rate():
    rows = [
        {"notional": 100.0, "pnl_net": 1.0, "pnl_gross": 1.0, "holding_days": 1.0, "won": True},
        {"notional": 100.0, "pnl_net": 1.0, "pnl_gross": 1.0, "holding_days": 1.0, "won": True},
        {"notional": 100.0, "pnl_net": -100.0, "pnl_gross": -100.0, "holding_days": 1.0, "won": False},
    ]
    m = compute_metrics(_trades_df(rows))
    assert m["n_trades"] == 3
    assert m["n_flips"] == 1
    assert m["win_rate"] == pytest.approx(2 / 3)
    assert m["flip_rate"] == pytest.approx(1 / 3)


def test_with_vs_without_flips_isolates_flip_damage():
    rows = [
        {"notional": 100.0, "pnl_net": 1.0, "pnl_gross": 1.0, "holding_days": 1.0, "won": True},
        {"notional": 100.0, "pnl_net": -100.0, "pnl_gross": -100.0, "holding_days": 1.0, "won": False},
    ]
    wv = compute_with_vs_without_flips(_trades_df(rows))
    assert wv["with_flips"]["total_pnl"] == pytest.approx(-99.0)
    assert wv["without_flips_ie_winners_only"]["total_pnl"] == pytest.approx(1.0)


def test_empty_trades_df_handled_gracefully():
    m = compute_metrics(pd.DataFrame())
    assert m["n_trades"] == 0
    assert math.isnan(m["win_rate"])


# ---------------------------------------------------------------------------
# Confidence intervals on the flip rate
# ---------------------------------------------------------------------------

def test_ci_is_wide_for_small_sample_zero_flips():
    lo, hi = wilson_interval(0, 50)
    assert lo == pytest.approx(0.0, abs=1e-9)
    assert hi > 0.05  # can't rule out a meaningfully nonzero true rate from 0/50


def test_ci_narrows_with_more_trades_same_rate():
    lo_small, hi_small = wilson_interval(2, 100)
    lo_big, hi_big = wilson_interval(20, 1000)
    assert (hi_small - lo_small) > (hi_big - lo_big)


def test_clopper_pearson_is_at_least_as_wide_as_wilson_for_rare_events():
    # exact CI is the conservative standard choice for small counts
    w_lo, w_hi = wilson_interval(2, 3000)
    cp_lo, cp_hi = clopper_pearson_interval(2, 3000)
    assert cp_hi - cp_lo >= w_hi - w_lo - 1e-6


def test_ci_bounds_are_valid_probabilities():
    for k, n in [(0, 10), (5, 5), (2, 3000), (1500, 3000)]:
        for lo, hi in [wilson_interval(k, n), clopper_pearson_interval(k, n)]:
            assert 0.0 <= lo <= hi <= 1.0


# ---------------------------------------------------------------------------
# Flip categorization heuristic
# ---------------------------------------------------------------------------

def test_categorize_flip_flags_disputed_status():
    m = {"id": "1", "question": "x", "umaResolutionStatus": "disputed", "umaResolutionStatuses": "[]"}
    assert categorize_flip(m)["heuristic_category"] == "disputed_resolution"


def test_categorize_flip_defaults_to_manual_review():
    m = {"id": "1", "question": "x", "umaResolutionStatus": "resolved", "umaResolutionStatuses": "[]"}
    assert categorize_flip(m)["heuristic_category"] == "needs_manual_review"
