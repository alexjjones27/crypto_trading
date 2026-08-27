"""Adapts the Polymarket "Final-1%" favorite-longshot-bias strategy to free
historical football (soccer) odds data from football-data.co.uk.

The core thesis carried over from the Polymarket project is the classic
favorite-longshot bias: heavy favorites are, on average, somewhat
UNDER-priced relative to their true win probability (bettors chase the
inflated payout on longshots, and bookmakers price the whole board -- not
each side independently -- so the mispricing they leave on the table tends
to sit at the favorite end). Polymarket tested this at the extreme end
(>99% implied probability, near-certain outcomes); this module tests the
same mechanism at a much wider, still-clearly-favorite band starting at
70% implied probability, using real bookmaker closing lines instead of an
order book.

Key translation from the Polymarket schema (see src/polymarket_final_pct.py
and scripts/run_kelly_backtest.py, whose run_sim/run_flat_sim engines this
module's trade records are built to feed *unmodified*):
  - "price" a bettor pays          -> 1 / decimal_odds on the favorite side
                                       (raw quoted odds, vig included -- the
                                       bookmaker's built-in margin plays the
                                       same role Polymarket's taker fee did,
                                       so fee_frac is left at 0.0 here rather
                                       than double-counting it).
  - "resolution"                    -> full-time result (FTR: H/D/A)
  - "report_bucket" (both the       -> league code (E0, D1, I1, ...), mirroring
     Bayesian walk-forward belief      the Polymarket project's choice to bucket
     AND the per-bucket capital        by category rather than by price band, so
     cap in run_sim/run_flat_sim)      the same tested engine code applies as-is.

Closing-line selection: Pinnacle (PSCH/PSCD/PSCA... "C" = closing) is used
whenever present -- it's the standard reference "sharp" book in the sports
betting literature (lowest average margin, first to move on new
information), the closest football analogue to a real order-book mid.
Falls back to Bet365, then the cross-bookmaker Max/Avg closing columns for
the small number of rows (~0.1%) where Pinnacle didn't quote that match.
"""
import csv
import glob
import os
from datetime import datetime, timedelta

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FOOTBALL_DATA_DIR = os.path.join(REPO, "data", "football_data")

# Preference order of (home, draw, away) closing-odds column triples.
CLOSING_COL_SETS = [
    ("PSCH", "PSCD", "PSCA"),
    ("B365CH", "B365CD", "B365CA"),
    ("MaxCH", "MaxCD", "MaxCA"),
    ("AvgCH", "AvgCD", "AvgCA"),
]

LEAGUE_NAMES = {
    "E0": "England - Premier League", "E1": "England - Championship",
    "SC0": "Scotland - Premiership", "D1": "Germany - Bundesliga",
    "I1": "Italy - Serie A", "SP1": "Spain - La Liga",
    "F1": "France - Ligue 1", "N1": "Netherlands - Eredivisie",
    "P1": "Portugal - Liga Portugal",
}


def _parse_date(s: str) -> datetime:
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    raise ValueError(f"unrecognized date format: {s!r}")


def _closing_odds(row: dict):
    """Returns (odds_h, odds_d, odds_a) from the first fully-populated
    closing-price column set, or None if no source had all three."""
    for h_col, d_col, a_col in CLOSING_COL_SETS:
        h, d, a = row.get(h_col), row.get(d_col), row.get(a_col)
        if h and d and a:
            try:
                return float(h), float(d), float(a)
            except ValueError:
                continue
    return None


def load_matches(data_dir: str = FOOTBALL_DATA_DIR) -> list[dict]:
    """Parses every cached football-data.co.uk CSV into one flat list of
    match dicts: league, kickoff_dt, ftr, odds_h/d/a (closing, vig included)."""
    matches = []
    for path in sorted(glob.glob(os.path.join(data_dir, "*.csv"))):
        league = os.path.basename(path).split("_")[0]
        with open(path, encoding="utf-8-sig", errors="replace", newline="") as f:
            for row in csv.DictReader(f):
                ftr = row.get("FTR")
                date_s = row.get("Date")
                if not ftr or ftr not in ("H", "D", "A") or not date_s:
                    continue
                odds = _closing_odds(row)
                if odds is None:
                    continue
                try:
                    kickoff = _parse_date(date_s)
                except ValueError:
                    continue
                matches.append({
                    "league": league,
                    "kickoff_dt": kickoff,
                    "ftr": ftr,
                    "odds_h": odds[0], "odds_d": odds[1], "odds_a": odds[2],
                    "home_team": row.get("HomeTeam", ""), "away_team": row.get("AwayTeam", ""),
                })
    return matches


def build_trades(matches: list[dict], threshold: float, resolve_lag_hours: float = 2.0,
                  side: str = "favorite") -> list[dict]:
    """Filters to matches where the FAVORITE's raw (vig-included) closing
    implied probability is >= threshold (the match-selection criterion never
    changes with `side`, so favorite and longshot backtests run over the
    identical population of games and are directly comparable), and builds
    trade records in the exact schema run_sim/run_flat_sim
    (scripts/run_kelly_backtest.py, scripts/run_flat_stake_backtest.py)
    expect. "Betting at the closing line" is the football analogue of
    Polymarket's "buy once price crosses the threshold shortly before
    resolution" -- both are the last tradeable price before the outcome is
    revealed.

    side="favorite" (default): back the lowest-odds outcome, as before.
    side="longshot": back the highest-odds (least likely) of the OTHER two
    outcomes instead -- the classic favorite-longshot-bias literature's
    other side of the same coin. Tests the hypothesis that if the favorite
    is overpriced, the longshot must be underpriced; see
    scripts/run_underdog_backtest.py for why that hypothesis doesn't survive
    contact with the data (both sides lose to the vig, longshot more so).
    """
    if side not in ("favorite", "longshot"):
        raise ValueError(f"side must be 'favorite' or 'longshot', got {side!r}")
    trades = []
    for m in matches:
        sides = [("H", m["odds_h"]), ("D", m["odds_d"]), ("A", m["odds_a"])]
        fav_side, fav_odds = min(sides, key=lambda x: x[1])  # lowest odds = favorite
        fav_price = 1.0 / fav_odds  # raw implied prob, vig included
        if fav_price < threshold:
            continue
        if side == "favorite":
            bet_side, bet_odds = fav_side, fav_odds
        else:
            non_fav = [s for s in sides if s[0] != fav_side]
            bet_side, bet_odds = max(non_fav, key=lambda x: x[1])  # longest odds of the rest
        price = 1.0 / bet_odds
        entry_dt = m["kickoff_dt"]
        trades.append({
            "league": m["league"],
            "category": m["league"],
            "report_bucket": m["league"],
            "question": f"{m['home_team']} vs {m['away_team']} ({m['league']}, {entry_dt.date()})",
            "entry_time": entry_dt.isoformat(),
            "resolution_time": (entry_dt + timedelta(hours=resolve_lag_hours)).isoformat(),
            "entry_dt": entry_dt,
            "resolve_dt": entry_dt + timedelta(hours=resolve_lag_hours),
            "entry_price": price,
            "fee_frac": 0.0,
            "depth_capped": False,
            "cap_shares": None,
            "excluded": False,
            "won": m["ftr"] == bet_side,
            "bet_side": bet_side,
            "bet_odds": bet_odds,
        })
    trades.sort(key=lambda r: r["entry_dt"])
    return trades
