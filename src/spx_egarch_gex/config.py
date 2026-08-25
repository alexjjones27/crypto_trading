"""Central configuration: paths, tickers, and the in-sample/validation/holdout split.

GEX/DIX history from SqueezeMetrics starts 2011-05-02 (confirmed by direct
fetch of https://squeezemetrics.com/monitor/static/DIX.csv), not 1990. The
split below is a PROPOSAL constrained by that start date and is pending
sign-off before being treated as final for any reported result.
"""

from __future__ import annotations

from pathlib import Path

# --- Paths -----------------------------------------------------------------

ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
RESULTS_DIR = ROOT_DIR / "results"

for _d in (RAW_DIR, PROCESSED_DIR, RESULTS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# --- Tickers / sources -------------------------------------------------------

SPX_TICKER = "^GSPC"  # S&P 500 index level (not SPY: no dividend-drop artifacts)
VIX_TICKER = "^VIX"

SQUEEZEMETRICS_DIX_URL = "https://squeezemetrics.com/monitor/static/DIX.csv"
CBOE_PUTCALL_URL = (
    "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"
)

# A plain browser User-Agent. Needed because (a) Yahoo Finance's chart API
# and SqueezeMetrics both 4xx/reset generic non-browser clients in some
# network environments, and (b) yfinance's default curl_cffi transport does
# TLS-fingerprint impersonation that does not tunnel through a TLS-terminating
# HTTPS proxy (seen in this sandbox: connection reset on every curl_cffi
# request). We force yfinance onto a plain `requests.Session` instead, which
# works fine through such a proxy and is what this constant is for.
HTTP_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# --- Data split --------------------------------------------------------------
# GEX history starts 2011-05-02, so the regime classifier and any strategy
# that depends on it cannot be evaluated before that date. Price/VIX-only
# work (e.g. the standalone EGARCH fit) can still use the full 1990- history.
#
# PROPOSED split (pending confirmation):
GEX_HISTORY_START = "2011-05-02"

SPLIT_IN_SAMPLE = ("2011-05-02", "2017-12-31")
SPLIT_VALIDATION = ("2018-01-01", "2020-12-31")
SPLIT_HOLDOUT = ("2021-01-01", None)  # None = through latest available data

# For the price/VIX-only EGARCH diagnostics (no GEX dependency), the longer
# 1990- history remains available and is used separately to justify model
# choice (Normal vs Student-t vs skew-t, residual diagnostics) on a longer
# sample before the GEX-constrained backtest window is applied.
EGARCH_DIAGNOSTIC_START = "1990-01-01"

# --- Strategy parameters (checkpoint 4) ----------------------------------
# Regime gate: lag applied to the sign(GEX) classifier before it can inform
# a trading decision (see checkpoint 3 -- 1-day lag is our best estimate of
# the free CSV's real-time availability, unverified beyond that).
REGIME_LAG = 1

# Vol targeting (shared by both sub-strategies): daily position size is
# rescaled to target this annualized vol using that day's EGARCH forecast,
# i.e. size_t = TARGET_VOL / cond_vol_forecast_t (annualized), capped at
# MAX_LEVERAGE. 15% approximates SPX's long-run realized vol, so typical
# exposure is close to 1x in "normal" conditions and shrinks/grows with the
# vol forecast.
TARGET_ANNUALIZED_VOL = 0.15
MAX_LEVERAGE = 2.0

# Mean-reversion sub-strategy (active only when regime == positive):
# entry/exit on a vol-standardized z-score of trailing n-day cumulative
# return.
MR_LOOKBACK_DAYS = 5
MR_ENTRY_Z = 1.5
MR_EXIT_Z = 0.25
MR_MAX_HOLD_DAYS = 10

# Vol-breakout sub-strategy (active only when regime == negative): entry on
# a realized-return breakout vs that day's EGARCH forecast vol, exit on a
# vol-scaled trailing stop (payoff-convexity edge, NOT a directional-
# persistence edge -- checkpoint 3 found no support for the latter).
BRK_ENTRY_SIGMA = 1.0
BRK_TRAILING_STOP_SIGMA = 1.5
BRK_MAX_HOLD_DAYS = 5

# Transaction costs: SPX itself isn't directly tradeable; assume execution
# via ES futures (deep liquidity). All-in round-trip cost (commission +
# half-spread + typical slippage) and an annualized financing spread
# charged only on leverage beyond 1x notional (borrowing cost for the
# levered portion of vol-targeted exposure).
TRANSACTION_COST_BPS = 2.0  # per unit of turnover (i.e. per 100% notional traded)
FINANCING_SPREAD_ANNUAL = 0.003  # 30bps/yr over the risk-free rate, on leverage > 1x
