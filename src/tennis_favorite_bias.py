"""Adapts the Polymarket "Final-1%" favorite-longshot-bias strategy to free
historical tennis odds data from tennis-data.co.uk (same publisher family
and format conventions as football-data.co.uk; see src/football_favorite_bias.py
for the fuller writeup of the translation this module reuses).

Tennis is a cleaner analogue than football in one respect: it's a genuine
two-outcome market (no draw), so "the favorite" and its raw implied
probability map onto Polymarket's binary YES/NO structure directly rather
than needing a 3-way argmin.

Column quirk specific to this dataset: PSW/PSL, B365W/B365L etc. are odds
for whoever actually WON and whoever actually LOST the match -- not "player
1" and "player 2". That's fine for what we need (which side was priced as
favorite, and did the favorite win), since both odds are genuinely pre-match
prices; we're only using the post-hoc W/L labels to figure out which
already-fixed price belonged to the favorite, not looking ahead to set the
price itself. The lower of the two odds is the favorite by construction; the
favorite "won" iff that lower-odds value sits in the W column.
"""
import os
from datetime import timedelta

import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TENNIS_DATA_DIR = os.path.join(REPO, "data", "tennis_data")

# (winner-col, loser-col) preference order, sharpest/most-complete first.
ODDS_COL_SETS = [("PSW", "PSL"), ("B365W", "B365L"), ("MaxW", "MaxL"), ("AvgW", "AvgL")]

EXCLUDED_COMMENTS = {"Walkover", "Awarded"}  # no genuine contest was played


def _odds(row) -> tuple[float, float] | None:
    for w_col, l_col in ODDS_COL_SETS:
        w, l = row.get(w_col), row.get(l_col)
        if pd.notna(w) and pd.notna(l) and w > 1.0 and l > 1.0:
            return float(w), float(l)
    return None


def load_matches(data_dir: str = TENNIS_DATA_DIR) -> list[dict]:
    """Parses every cached tennis-data.co.uk file into one flat list of
    match dicts: tour, surface, match_dt, fav_won, fav_odds."""
    matches = []
    if not os.path.isdir(data_dir):
        return matches
    for fn in sorted(os.listdir(data_dir)):
        if not (fn.endswith(".xls") or fn.endswith(".xlsx")):
            continue
        tour = "ATP" if fn.startswith("ATP") else "WTA"
        df = pd.read_excel(os.path.join(data_dir, fn))
        for _, row in df.iterrows():
            comment = row.get("Comment")
            if comment in EXCLUDED_COMMENTS:
                continue
            date = row.get("Date")
            if pd.isna(date):
                continue
            odds = _odds(row)
            if odds is None:
                continue
            w_odds, l_odds = odds
            fav_odds = min(w_odds, l_odds)
            fav_won = w_odds <= l_odds  # favorite is whichever side had the lower odds
            surface = row.get("Surface") if pd.notna(row.get("Surface")) else "Unknown"
            matches.append({
                "tour": tour,
                "surface": surface,
                "match_dt": pd.Timestamp(date).to_pydatetime(),
                "fav_odds": fav_odds,
                "fav_won": bool(fav_won),
                "winner": row.get("Winner", ""), "loser": row.get("Loser", ""),
                "tournament": row.get("Tournament", ""),
            })
    return matches


def build_trades(matches: list[dict], threshold: float, resolve_lag_hours: float = 3.0) -> list[dict]:
    """Same schema translation as football_favorite_bias.build_trades, feeding
    run_sim/run_flat_sim (scripts/run_kelly_backtest.py,
    scripts/run_flat_stake_backtest.py) unmodified. report_bucket is
    tour+surface (e.g. "ATP-Hard") rather than football's per-league bucket,
    since surface is the analogous real source of heterogeneity in tennis
    (clay vs. hard vs. grass materially changes how often favorites hold)."""
    trades = []
    for m in matches:
        price = 1.0 / m["fav_odds"]
        if price < threshold:
            continue
        entry_dt = m["match_dt"]
        bucket = f"{m['tour']}-{m['surface']}"
        trades.append({
            "tour": m["tour"], "surface": m["surface"],
            "category": bucket, "report_bucket": bucket,
            "question": f"{m['winner']} vs {m['loser']} ({m['tournament']}, {entry_dt.date()})",
            "entry_time": entry_dt.isoformat(),
            "resolution_time": (entry_dt + timedelta(hours=resolve_lag_hours)).isoformat(),
            "entry_dt": entry_dt,
            "resolve_dt": entry_dt + timedelta(hours=resolve_lag_hours),
            "entry_price": price,
            "fee_frac": 0.0,
            "depth_capped": False,
            "cap_shares": None,
            "excluded": False,
            "won": m["fav_won"],
            "fav_odds": m["fav_odds"],
        })
    trades.sort(key=lambda r: r["entry_dt"])
    return trades
