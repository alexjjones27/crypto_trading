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
# return. Lookback=3 (not 5), originally picked in checkpoint 4b from a
# sensitivity grid run on the FULL 2011-2026 sample -- since found (leakage
# check, see results/leakage_check.txt) to have used data through the
# entire planned holdout window, so that selection was contaminated.
# Re-run as a nested selection (grid computed on in-sample
# 2011-2017 only, decision made on validation-2018-2020-only performance,
# holdout never read): lookback=3 remains the only lookback with a
# positive mean trade return at every entry_z on validation data too, so
# it survives the leak-free re-test BY THE SAME CRITERION originally used
# -- but the supporting evidence is much weaker under the honest
# accounting: small samples (3-80 trades per cell within a single 3-7 year
# window) and no t-stat above ~1.9 anywhere in either the in-sample or
# validation grid. Kept as the best-supported (not contradicted) choice,
# but flagged as fragile pending checkpoint 5's proper significance
# testing on the full walk-forward -- treat this as a working choice, not
# a validated one. entry_z/exit_z/max_hold left at their original a priori
# values throughout (never grid-searched).
MR_LOOKBACK_DAYS = 3
MR_ENTRY_Z = 1.5
MR_EXIT_Z = 0.25
MR_MAX_HOLD_DAYS = 10

# Vol-breakout sub-strategy (active only when regime == negative): entry on
# a realized-return breakout vs that day's EGARCH forecast vol, exit on a
# vol-scaled trailing stop. Direction is MOMENTUM (follow the breakout) --
# checkpoint 4b originally flipped this to contrarian based on an A/B test
# that the leakage check found was run on the full 2011-2026 sample
# (contaminated: touches the entire planned holdout). Re-run as a nested
# selection (A/B computed on in-sample 2011-2017, decision made on
# validation-2018-2020-only performance, holdout never read): momentum
# beats contrarian on BOTH in-sample (mean trade return +0.27% vs -0.55%)
# and validation (+0.09% vs -0.61%) -- the opposite of the contaminated
# result. Reverted to momentum. The "contrarian wins" finding was
# apparently driven by something specific to 2021-2026 data that the
# leaked test was implicitly evaluated on, not a real in-sample/validation
# effect -- a concrete illustration of why the leakage mattered, not just
# a technicality.
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
