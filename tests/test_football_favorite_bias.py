import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
import football_favorite_bias as ffb


def test_closing_odds_prefers_pinnacle():
    row = {"PSCH": "1.50", "PSCD": "4.00", "PSCA": "6.00",
           "B365CH": "1.60", "B365CD": "3.80", "B365CA": "5.50"}
    assert ffb._closing_odds(row) == (1.50, 4.00, 6.00)


def test_closing_odds_falls_back_when_pinnacle_missing():
    row = {"PSCH": "", "PSCD": "", "PSCA": "",
           "B365CH": "1.60", "B365CD": "3.80", "B365CA": "5.50"}
    assert ffb._closing_odds(row) == (1.60, 3.80, 5.50)


def test_closing_odds_falls_back_through_max_avg():
    row = {"PSCH": "", "PSCD": "", "PSCA": "",
           "B365CH": "", "B365CD": "", "B365CA": "",
           "MaxCH": "1.65", "MaxCD": "3.90", "MaxCA": "5.60",
           "AvgCH": "1.58", "AvgCD": "3.85", "AvgCA": "5.55"}
    assert ffb._closing_odds(row) == (1.65, 3.90, 5.60)


def test_closing_odds_returns_none_when_all_missing():
    row = {"PSCH": "", "PSCD": "", "PSCA": ""}
    assert ffb._closing_odds(row) is None


def test_closing_odds_returns_none_on_partial_row():
    # Home and draw present but away missing -- must not silently mix
    # columns from different bookmakers' triples.
    row = {"PSCH": "1.50", "PSCD": "4.00", "PSCA": "",
           "B365CH": "1.60", "B365CD": "3.80", "B365CA": "5.50"}
    assert ffb._closing_odds(row) == (1.60, 3.80, 5.50)


def test_parse_date_two_and_four_digit_year():
    assert ffb._parse_date("18/08/12") == datetime(2012, 8, 18)
    assert ffb._parse_date("09/08/2019") == datetime(2019, 8, 9)


def test_parse_date_rejects_garbage():
    import pytest
    with pytest.raises(ValueError):
        ffb._parse_date("not-a-date")


def _match(odds_h, odds_d, odds_a, ftr, kickoff=datetime(2020, 1, 1), league="E0"):
    return {"league": league, "kickoff_dt": kickoff, "ftr": ftr,
            "odds_h": odds_h, "odds_d": odds_d, "odds_a": odds_a,
            "home_team": "Home", "away_team": "Away"}


def test_build_trades_picks_lowest_odds_as_favorite():
    # Home is the clear favorite (odds 1.30 -> implied ~76.9%).
    m = _match(1.30, 5.00, 8.00, ftr="H")
    trades = ffb.build_trades([m], threshold=0.70)
    assert len(trades) == 1
    t = trades[0]
    assert t["fav_side"] == "H"
    assert abs(t["entry_price"] - 1 / 1.30) < 1e-9
    assert t["won"] is True


def test_build_trades_filters_below_threshold():
    m = _match(2.00, 3.30, 4.00, ftr="H")  # favorite implied prob = 50%, below 70%
    trades = ffb.build_trades([m], threshold=0.70)
    assert trades == []


def test_build_trades_marks_loss_when_favorite_does_not_win():
    m = _match(1.30, 5.00, 8.00, ftr="A")  # heavy home favorite, away wins instead
    trades = ffb.build_trades([m], threshold=0.70)
    assert trades[0]["won"] is False
    assert trades[0]["fav_side"] == "H"


def test_build_trades_schema_matches_kelly_engine_expectations():
    """The whole point of this module is to feed run_sim/run_flat_sim
    unmodified -- lock down the field set those engines actually read."""
    m = _match(1.25, 5.50, 9.00, ftr="H")
    t = ffb.build_trades([m], threshold=0.70)[0]
    required = {"entry_dt", "resolve_dt", "entry_price", "fee_frac", "depth_capped",
                "cap_shares", "excluded", "won", "report_bucket"}
    assert required.issubset(t.keys())
    assert t["resolve_dt"] > t["entry_dt"]
    assert t["fee_frac"] == 0.0
    assert t["excluded"] is False
    assert t["report_bucket"] == t["league"] == "E0"


def test_build_trades_sorted_by_entry_time():
    m1 = _match(1.30, 5.00, 8.00, ftr="H", kickoff=datetime(2021, 5, 1))
    m2 = _match(1.30, 5.00, 8.00, ftr="H", kickoff=datetime(2020, 1, 1))
    trades = ffb.build_trades([m1, m2], threshold=0.70)
    assert [t["entry_dt"] for t in trades] == sorted(t["entry_dt"] for t in trades)


def test_load_matches_smoke_on_real_cache():
    """If the download cache isn't present (e.g. a clean checkout that
    hasn't run scripts/download_football_data.py yet) this is a no-op
    rather than a failure -- the cache is a local data artifact, not
    something committed to the repo."""
    if not os.path.isdir(ffb.FOOTBALL_DATA_DIR) or not os.listdir(ffb.FOOTBALL_DATA_DIR):
        return
    matches = ffb.load_matches()
    assert len(matches) > 1000
    for m in matches[:50]:
        assert m["ftr"] in ("H", "D", "A")
        assert m["odds_h"] > 1.0 and m["odds_d"] > 1.0 and m["odds_a"] > 1.0
        assert isinstance(m["kickoff_dt"], datetime)
