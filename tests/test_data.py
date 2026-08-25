"""Smoke tests for the cached data panel (no network access required)."""

import pandas as pd
import pytest

from spx_egarch_gex import config

PANEL_PATH = config.PROCESSED_DIR / "panel.csv"

pytestmark = pytest.mark.skipif(
    not PANEL_PATH.exists(),
    reason="panel.csv not built yet; run `python -m spx_egarch_gex.data.build_dataset` first",
)


@pytest.fixture(scope="module")
def panel() -> pd.DataFrame:
    return pd.read_csv(PANEL_PATH, index_col="date", parse_dates=["date"])


def test_panel_has_expected_columns(panel):
    expected = {"spx_close", "spx_log_ret", "vix_close", "dix", "gex", "gex_price"}
    assert expected.issubset(panel.columns)


def test_panel_index_is_sorted_and_unique(panel):
    assert panel.index.is_monotonic_increasing
    assert panel.index.is_unique


def test_gex_covered_window_has_no_gaps(panel):
    sub = panel.loc[config.GEX_HISTORY_START :]
    complete = sub.dropna(subset=["spx_close", "vix_close", "gex", "dix"])
    assert len(complete) == len(sub), "unexpected missing values inside GEX-covered window"


def test_spx_vix_start_before_gex_history(panel):
    spx_start = panel["spx_close"].dropna().index.min()
    gex_start = panel["gex"].dropna().index.min()
    assert spx_start < gex_start


def test_spx_price_matches_squeezemetrics_price_closely(panel):
    sub = panel.dropna(subset=["spx_close", "gex_price"])
    rel_diff = (sub["spx_close"] - sub["gex_price"]).abs() / sub["spx_close"]
    assert rel_diff.mean() < 0.001
    assert (rel_diff > 0.01).sum() == 0
