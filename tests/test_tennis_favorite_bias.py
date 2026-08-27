import os
import sys
from datetime import datetime

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
import tennis_favorite_bias as tfb


def test_odds_prefers_pinnacle():
    row = pd.Series({"PSW": 1.40, "PSL": 3.00, "B365W": 1.45, "B365L": 2.90})
    assert tfb._odds(row) == (1.40, 3.00)


def test_odds_falls_back_when_pinnacle_missing():
    row = pd.Series({"PSW": None, "PSL": None, "B365W": 1.45, "B365L": 2.90})
    assert tfb._odds(row) == (1.45, 2.90)


def test_odds_falls_back_through_max_avg():
    row = pd.Series({"PSW": None, "PSL": None, "B365W": None, "B365L": None,
                      "MaxW": 1.50, "MaxL": 2.80, "AvgW": 1.42, "AvgL": 2.70})
    assert tfb._odds(row) == (1.50, 2.80)


def test_odds_returns_none_when_all_missing():
    row = pd.Series({"PSW": None, "PSL": None})
    assert tfb._odds(row) is None


def test_odds_rejects_non_positive_or_subunity_values():
    # A malformed row (e.g. odds of 0 or 1.0) must not be treated as valid.
    row = pd.Series({"PSW": 0.0, "PSL": 3.00, "B365W": 1.45, "B365L": 2.90})
    assert tfb._odds(row) == (1.45, 2.90)


def _match(w_odds, l_odds, fav_won, dt=datetime(2020, 1, 1), tour="ATP", surface="Hard"):
    fav_odds = min(w_odds, l_odds)
    return {"tour": tour, "surface": surface, "match_dt": dt, "fav_odds": fav_odds,
            "fav_won": fav_won, "winner": "A", "loser": "B", "tournament": "Test Open"}


def test_build_trades_filters_below_threshold():
    m = _match(2.00, 2.00, fav_won=True)  # implied prob = 50%, below 70%
    assert tfb.build_trades([m], threshold=0.70) == []


def test_build_trades_marks_loss_when_favorite_does_not_win():
    m = _match(1.30, 5.00, fav_won=False)
    t = tfb.build_trades([m], threshold=0.70)[0]
    assert t["won"] is False
    assert abs(t["entry_price"] - 1 / 1.30) < 1e-9


def test_build_trades_marks_win_when_favorite_wins():
    m = _match(1.20, 6.00, fav_won=True)
    t = tfb.build_trades([m], threshold=0.70)[0]
    assert t["won"] is True


def test_build_trades_bucket_is_tour_and_surface():
    m = _match(1.20, 6.00, fav_won=True, tour="WTA", surface="Clay")
    t = tfb.build_trades([m], threshold=0.70)[0]
    assert t["report_bucket"] == "WTA-Clay"


def test_build_trades_schema_matches_kelly_engine_expectations():
    m = _match(1.15, 7.00, fav_won=True)
    t = tfb.build_trades([m], threshold=0.70)[0]
    required = {"entry_dt", "resolve_dt", "entry_price", "fee_frac", "depth_capped",
                "cap_shares", "excluded", "won", "report_bucket"}
    assert required.issubset(t.keys())
    assert t["resolve_dt"] > t["entry_dt"]
    assert t["fee_frac"] == 0.0
    assert t["excluded"] is False


def test_build_trades_sorted_by_entry_time():
    m1 = _match(1.20, 6.00, fav_won=True, dt=datetime(2021, 5, 1))
    m2 = _match(1.20, 6.00, fav_won=True, dt=datetime(2020, 1, 1))
    trades = tfb.build_trades([m1, m2], threshold=0.70)
    assert [t["entry_dt"] for t in trades] == sorted(t["entry_dt"] for t in trades)


def test_load_matches_smoke_on_real_cache():
    if not os.path.isdir(tfb.TENNIS_DATA_DIR) or not os.listdir(tfb.TENNIS_DATA_DIR):
        return
    matches = tfb.load_matches()
    assert len(matches) > 1000
    for m in matches[:50]:
        assert m["fav_odds"] >= 1.0
        assert isinstance(m["fav_won"], bool)
        assert isinstance(m["match_dt"], datetime)
