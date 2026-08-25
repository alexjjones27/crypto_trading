"""SqueezeMetrics DIX/GEX ingestion, with local CSV caching.

Source: https://squeezemetrics.com/monitor/static/DIX.csv (the free CSV
backing the public https://squeezemetrics.com/monitor/dix chart; confirmed
reachable and parseable by direct fetch).

Columns as published: date, price, dix, gex
    date  : trading date (S&P 500 dark-pool/options session date)
    price : S&P 500 close SqueezeMetrics used for that row
    dix   : Dark Index (dollar-weighted dark-pool buy indicator, 0-1 range)
    gex   : dealer Gamma Exposure, USD notional (can be negative)

History observed to start 2011-05-02. This is real aggregate dealer gamma
exposure (SqueezeMetrics' own methodology from OCC/OPRA option data), not a
VIX-minus-realized-vol proxy.
"""

from __future__ import annotations

import logging

import pandas as pd
import requests

from spx_egarch_gex import config

logger = logging.getLogger(__name__)


def fetch_gex_raw() -> pd.DataFrame:
    resp = requests.get(
        config.SQUEEZEMETRICS_DIX_URL,
        headers={"User-Agent": config.HTTP_USER_AGENT},
        timeout=30,
    )
    resp.raise_for_status()
    from io import StringIO

    df = pd.read_csv(StringIO(resp.text))
    expected_cols = {"date", "price", "dix", "gex"}
    if not expected_cols.issubset(df.columns):
        raise RuntimeError(
            f"Unexpected DIX.csv columns {list(df.columns)}; expected {expected_cols}"
        )
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    return df


def fetch_and_cache_gex(cache_name: str = "gex.csv", refresh: bool = False) -> pd.DataFrame:
    path = config.RAW_DIR / cache_name
    if path.exists() and not refresh:
        df = pd.read_csv(path, index_col="date", parse_dates=["date"])
        logger.info("Loaded cached GEX/DIX (%d rows) from %s", len(df), path)
        return df

    df = fetch_gex_raw()
    df.to_csv(path)
    logger.info(
        "Fetched and cached GEX/DIX (%d rows, %s to %s) to %s",
        len(df),
        df.index.min().date(),
        df.index.max().date(),
        path,
    )
    return df
