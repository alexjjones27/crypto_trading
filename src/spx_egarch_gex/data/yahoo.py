"""Yahoo Finance price/VIX ingestion, with local CSV caching.

yfinance's default transport (curl_cffi, doing TLS-fingerprint impersonation)
can fail with connection resets behind a TLS-terminating HTTPS proxy even
when the destination is fully reachable. We route yfinance through a plain
``requests.Session`` instead, which is unaffected by that and works
identically on a normal (non-proxied) machine.
"""

from __future__ import annotations

import logging

import pandas as pd
import requests
import yfinance as yf

from spx_egarch_gex import config

logger = logging.getLogger(__name__)


def _session() -> requests.Session:
    sess = requests.Session()
    sess.headers.update({"User-Agent": config.HTTP_USER_AGENT})
    return sess


def fetch_yahoo_series(ticker: str, start: str = "1990-01-01") -> pd.DataFrame:
    """Download full daily OHLCV history for `ticker` from Yahoo Finance."""
    df = yf.download(
        ticker,
        start=start,
        progress=False,
        session=_session(),
        auto_adjust=False,
    )
    if df.empty:
        raise RuntimeError(f"yfinance returned no data for {ticker}")
    # yfinance >=0.2.4x returns a MultiIndex column frame even for a single
    # ticker; flatten it.
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.index.name = "date"
    df.index = pd.to_datetime(df.index).tz_localize(None)
    return df


def fetch_and_cache(
    ticker: str, cache_name: str, start: str = "1990-01-01", refresh: bool = False
) -> pd.DataFrame:
    """Fetch `ticker` and cache/read from data/raw/<cache_name>.csv."""
    path = config.RAW_DIR / cache_name
    if path.exists() and not refresh:
        df = pd.read_csv(path, index_col="date", parse_dates=["date"])
        logger.info("Loaded cached %s (%d rows) from %s", ticker, len(df), path)
        return df

    df = fetch_yahoo_series(ticker, start=start)
    df.to_csv(path)
    logger.info("Fetched and cached %s (%d rows) to %s", ticker, len(df), path)
    return df


def fetch_spx(start: str = "1990-01-01", refresh: bool = False) -> pd.DataFrame:
    return fetch_and_cache(config.SPX_TICKER, "spx.csv", start=start, refresh=refresh)


def fetch_vix(start: str = "1990-01-01", refresh: bool = False) -> pd.DataFrame:
    return fetch_and_cache(config.VIX_TICKER, "vix.csv", start=start, refresh=refresh)
