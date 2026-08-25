"""Spot-perp funding rate arbitrage backtest for Hyperliquid (BTC, ETH, SOL).

Historical backtest only -- no live trading, no order execution, no API
keys. Pulls hourly funding-rate history from Hyperliquid's public `/info`
endpoint, derives a fee/slippage-based breakeven threshold, and backtests a
delta-neutral "collect funding" strategy (long spot / short perp when
funding is positive and clears breakeven; the reverse when it is negative)
run walk-forward with no lookahead.

The module is organized into clearly separated sections so any one part can
be swapped without touching the others:

    1. DATA FETCH      -- network + on-disk cache only, no strategy logic.
    2. FEES / BREAKEVEN -- pure functions of a cost assumption.
    3. POSITION SIZING  -- pluggable notional-sizing functions.
    4. SIGNAL + BACKTEST -- no-lookahead position generation and P&L.
    5. ROTATION VARIANT -- capital rotated across BTC/ETH/SOL.
    6. METRICS / LIQUIDITY FLAGS
    7. PLOTS / REPORT
    8. MAIN

Key data quirk discovered from the live API (see README section in
`main()`'s docstring / the written report): Hyperliquid funding settled
every 8 hours from each asset's May 2023 listing until ~2023-06-08, then
switched to hourly settlement, which is what "funding settles hourly" on
Hyperliquid today refers to. The pipeline does not hardcode either
convention -- it derives the settlement cadence at each timestamp from the
gap between consecutive records and annualizes accordingly.
"""

from __future__ import annotations

import json
import math
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Paths / constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = REPO_ROOT / "data" / "raw" / "hyperliquid"
RESULTS_DIR = REPO_ROOT / "results" / "hyperliquid_funding_arb"
PLOTS_DIR = RESULTS_DIR / "plots"

HYPERLIQUID_INFO_URL = "https://api.hyperliquid.xyz/info"
COINS = ["BTC", "ETH", "SOL"]
HOURS_PER_YEAR = 24 * 365
PAGE_LIMIT = 500  # observed cap on records returned per fundingHistory call
# Conservative lower bound predating every coin's actual Hyperliquid listing
# (confirmed live: BTC/ETH/SOL all first have funding data on 2023-05-12).
# The fetch loop discovers the real start from what the API returns -- this
# constant only needs to be *early enough*, not exact.
EARLIEST_POSSIBLE_MS = 1_672_531_200_000  # 2023-01-01T00:00:00Z


# ---------------------------------------------------------------------------
# 1. DATA FETCH (network + disk cache -- no strategy logic here)
# ---------------------------------------------------------------------------

def _post_info(payload: dict, retries: int = 5, timeout: float = 30.0) -> object:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        HYPERLIQUID_INFO_URL,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last_err = exc
            time.sleep(min(2 ** attempt, 20))
    raise RuntimeError(f"Hyperliquid API request failed after {retries} retries: {last_err}")


def fetch_funding_page(coin: str, start_ms: int, end_ms: int) -> list[dict]:
    """One raw call to `fundingHistory`. Confirmed live: returns up to 500
    records `[{"coin", "fundingRate", "premium", "time"}, ...]` sorted by
    time ascending, capped at 500 regardless of the requested range."""
    return _post_info(
        {"type": "fundingHistory", "coin": coin, "startTime": start_ms, "endTime": end_ms}
    )


def _cache_path(coin: str, cache_dir: Path) -> Path:
    return cache_dir / f"funding_{coin}.json"


def load_cached_funding(coin: str, cache_dir: Path = CACHE_DIR) -> list[dict]:
    path = _cache_path(coin, cache_dir)
    if path.exists():
        return json.loads(path.read_text())
    return []


def save_cached_funding(coin: str, records: list[dict], cache_dir: Path = CACHE_DIR) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    _cache_path(coin, cache_dir).write_text(json.dumps(records))


def fetch_full_funding_history(
    coin: str,
    cache_dir: Path = CACHE_DIR,
    listing_start_ms: int = EARLIEST_POSSIBLE_MS,
    end_ms: Optional[int] = None,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Pull the complete funding-rate history for `coin`, using and updating
    an on-disk cache keyed by coin so re-runs only fetch records newer than
    what's already cached (never re-hits the API for old history)."""
    if end_ms is None:
        end_ms = int(time.time() * 1000)

    cached = [] if force_refresh else load_cached_funding(coin, cache_dir)
    records = list(cached)
    cur_start = records[-1]["time"] + 1 if records else listing_start_ms

    while cur_start < end_ms:
        page = fetch_funding_page(coin, cur_start, end_ms)
        if not page:
            break
        records.extend(page)
        last_t = page[-1]["time"]
        if len(page) < PAGE_LIMIT or last_t <= cur_start:
            break
        cur_start = last_t + 1

    save_cached_funding(coin, records, cache_dir)
    return _records_to_frame(records)


def _records_to_frame(records: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(records).drop_duplicates(subset="time").sort_values("time").reset_index(drop=True)
    df["fundingRate"] = df["fundingRate"].astype(float)
    df["premium"] = df["premium"].astype(float)
    df["timestamp"] = pd.to_datetime(df["time"], unit="ms", utc=True)
    return df


# ---------------------------------------------------------------------------
# 2. FEES / BREAKEVEN (pure functions -- no data dependency)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FeeSchedule:
    """Hyperliquid base (Tier 0, no volume/staking discount) fee schedule,
    confirmed against https://hyperliquid.gitbook.io/hyperliquid-docs on
    2026-08-25. Re-check before relying on this for anything live."""

    perp_maker_bps: float = 1.5   # 0.015%
    perp_taker_bps: float = 4.5   # 0.045%
    spot_maker_bps: float = 4.0   # 0.040%
    spot_taker_bps: float = 7.0   # 0.070%


DEFAULT_FEES = FeeSchedule()


@dataclass(frozen=True)
class CostAssumptions:
    """Everything needed to price one round trip. `fill_type` selects the
    best-case (maker/maker) or worst-case (taker/taker) fill assumption on
    both legs, per the task spec."""

    fees: FeeSchedule = DEFAULT_FEES
    slippage_bps_per_leg: float = 2.0
    fill_type: str = "maker"  # "maker" | "taker"

    def _leg_fee_bps(self, leg: str) -> float:
        if leg == "spot":
            return self.fees.spot_maker_bps if self.fill_type == "maker" else self.fees.spot_taker_bps
        if leg == "perp":
            return self.fees.perp_maker_bps if self.fill_type == "maker" else self.fees.perp_taker_bps
        raise ValueError(leg)

    def one_way_cost_bps(self) -> float:
        """Cost of a single entry (or single exit): one spot fill + one perp
        fill, each with its own slippage."""
        return self._leg_fee_bps("spot") + self._leg_fee_bps("perp") + 2 * self.slippage_bps_per_leg

    def round_trip_cost_bps(self) -> float:
        return 2 * self.one_way_cost_bps()

    def round_trip_cost_frac(self) -> float:
        return self.round_trip_cost_bps() / 1e4


def breakeven_hourly_rate(costs: CostAssumptions, horizon_hours: float) -> float:
    """Hourly funding rate at which round-trip costs are exactly recouped if
    the position is held for `horizon_hours`. This amortization horizon is
    an explicit, configurable modeling choice (not the actual exit rule) --
    it answers "how many hours of funding income do we require the round
    trip to pay for itself in before it's worth entering at all"."""
    return costs.round_trip_cost_frac() / horizon_hours


def breakeven_annualized_rate(costs: CostAssumptions, horizon_hours: float) -> float:
    return breakeven_hourly_rate(costs, horizon_hours) * HOURS_PER_YEAR


# ---------------------------------------------------------------------------
# 3. POSITION SIZING (pluggable)
# ---------------------------------------------------------------------------
# A sizer is `Callable[[pd.Series], float]`: given the current row (with
# access to any precomputed columns), return the notional to trade. The base
# case uses a fixed notional per trade. `vol_adjusted_sizer` is a working
# alternative that scales notional inversely with trailing realized
# volatility of the funding-rate signal itself -- a proxy, since this
# pipeline only fetches funding history, not spot price history. A real
# vol-adjusted sizer would use underlying spot price vol; this demonstrates
# the pluggable interface without inventing an unrequested data fetch.

Sizer = Callable[[pd.Series], float]


def fixed_notional_sizer(notional: float) -> Sizer:
    def _sizer(row: pd.Series) -> float:
        return notional
    return _sizer


def add_trailing_funding_vol(df: pd.DataFrame, lookback_periods: int = 24 * 30) -> pd.DataFrame:
    df = df.copy()
    df["trailing_funding_vol"] = df["hourly_rate"].rolling(lookback_periods, min_periods=24).std()
    return df


def vol_adjusted_sizer(
    base_notional: float,
    target_annualized_vol: float = 0.05,
    min_scale: float = 0.25,
    max_scale: float = 2.0,
) -> Sizer:
    """Illustrative alternative sizer: shrinks notional when the funding
    signal has recently been more volatile than `target_annualized_vol`,
    scales it up (bounded) when it has been calmer. Requires
    `add_trailing_funding_vol` to have been run on the frame first."""

    def _sizer(row: pd.Series) -> float:
        vol = row.get("trailing_funding_vol", np.nan)
        if vol is None or not np.isfinite(vol) or vol <= 0:
            return base_notional
        annualized_vol = vol * math.sqrt(HOURS_PER_YEAR)
        scale = target_annualized_vol / annualized_vol
        scale = min(max(scale, min_scale), max_scale)
        return base_notional * scale

    return _sizer


# ---------------------------------------------------------------------------
# 4. SIGNAL + BACKTEST (single asset)
# ---------------------------------------------------------------------------

@dataclass
class StrategyConfig:
    buffer_multiplier: float = 2.0          # entry requires |rate| > buffer * breakeven
    breakeven_horizon_hours: float = 24.0   # amortization horizon for breakeven (see above)
    max_holding_hours: Optional[float] = None  # None = no cap, exit only on breakeven cross
    notional: float = 10_000.0
    illiquidity_run_hours: float = 24 * 14  # flag same-sign funding runs longer than this


def add_annualized_rate(df: pd.DataFrame) -> pd.DataFrame:
    """Derive the settlement cadence directly from consecutive timestamps
    (no hardcoded 1h/8h assumption) and annualize `fundingRate` accordingly.
    This is what lets the pipeline cross the live 8h->1h regime switch
    (~2023-06-08) without special-casing it. Fully causal: period_hours[i]
    is the backward gap time[i]-time[i-1], known once row i has printed."""
    df = df.copy()
    dt_hours = df["time"].diff() / 3_600_000.0
    if len(df) > 1:
        dt_hours.iloc[0] = dt_hours.iloc[1]  # only affects the single earliest listing row
    else:
        dt_hours.iloc[0] = 1.0
    df["period_hours"] = dt_hours
    df["hourly_rate"] = df["fundingRate"] / df["period_hours"]
    df["annualized_rate"] = df["hourly_rate"] * HOURS_PER_YEAR
    return df


def generate_positions_and_backtest(
    df: pd.DataFrame,
    costs: CostAssumptions,
    cfg: StrategyConfig,
    sizer: Optional[Sizer] = None,
) -> dict:
    """Walk-forward, no-lookahead signal + P&L in one pass.

    Timing convention: at row i we know `annualized_rate[i]` (just settled)
    and everything before it. We decide the position to CARRY into the
    interval (t_i, t_{i+1}], which is what earns/pays `fundingRate[i+1]`
    when it settles. So `held_side[i] = side[i-1]`, and
    `funding_pnl[i] = held_side[i] * fundingRate[i] * notional`.
    Entry/exit fees are charged on the row where the position changes,
    sized off that row's notional.

    Entry:  flat -> requires |annualized_rate[i]| > buffer_multiplier * breakeven.
    Exit:   in position -> triggered by (a) |annualized_rate[i]| < breakeven,
            (b) funding direction flips sign, or (c) max_holding_hours reached.
    A sign flip closes the old side and can immediately open the new one on
    the same row if it separately clears the entry threshold (charged as a
    full round trip: one exit + one entry).
    """
    sizer = sizer or fixed_notional_sizer(cfg.notional)
    be = breakeven_annualized_rate(costs, cfg.breakeven_horizon_hours)
    entry_threshold = cfg.buffer_multiplier * be

    n = len(df)
    rate = df["annualized_rate"].to_numpy()
    period_hours = df["period_hours"].to_numpy()

    side = np.zeros(n, dtype=int)          # position decided at i, held into (t_i, t_{i+1}]
    is_entry = np.zeros(n, dtype=bool)
    is_exit = np.zeros(n, dtype=bool)
    hours_since_entry_at_i = np.zeros(n, dtype=float)  # realized holding duration through row i

    trades: list[dict] = []
    cur_side = 0
    cur_hours = 0.0
    entry_idx: Optional[int] = None

    for i in range(n):
        r = rate[i]
        if cur_side != 0:
            cur_hours += period_hours[i]

        if not np.isnan(r):
            target_sign = 1 if r > 0 else (-1 if r < 0 else 0)
            if cur_side == 0:
                if abs(r) > entry_threshold and target_sign != 0:
                    cur_side = target_sign
                    cur_hours = 0.0
                    entry_idx = i
                    is_entry[i] = True
            else:
                flipped = target_sign != 0 and target_sign != cur_side
                below_be = abs(r) < be
                maxed_out = cfg.max_holding_hours is not None and cur_hours >= cfg.max_holding_hours
                if flipped or below_be or maxed_out:
                    is_exit[i] = True
                    trades.append(
                        {
                            "entry_idx": entry_idx,
                            "exit_idx": i,
                            "side": cur_side,
                            "hours_held": cur_hours,
                            "exit_reason": "flip" if flipped else ("max_holding" if maxed_out else "below_breakeven"),
                        }
                    )
                    cur_side = 0
                    cur_hours = 0.0
                    entry_idx = None
                    if flipped and abs(r) > entry_threshold:
                        cur_side = target_sign
                        cur_hours = 0.0
                        entry_idx = i
                        is_entry[i] = True

        side[i] = cur_side
        hours_since_entry_at_i[i] = cur_hours

    if cur_side != 0 and entry_idx is not None:
        trades.append(
            {
                "entry_idx": entry_idx,
                "exit_idx": None,
                "side": cur_side,
                "hours_held": cur_hours,
                "exit_reason": "open_at_end_of_data",
            }
        )

    df = df.copy()
    df["side"] = side
    df["is_entry"] = is_entry
    df["is_exit"] = is_exit
    df["hours_since_entry"] = hours_since_entry_at_i
    df["breakeven_annualized"] = be
    df["entry_threshold_annualized"] = entry_threshold

    df["notional"] = df.apply(sizer, axis=1)
    df["held_side"] = df["side"].shift(1).fillna(0).astype(int)
    df["funding_pnl"] = df["held_side"] * df["fundingRate"] * df["notional"]

    one_way_frac = costs.one_way_cost_bps() / 1e4
    df["fees_paid"] = (df["is_entry"].astype(int) + df["is_exit"].astype(int)) * df["notional"] * one_way_frac

    df["pnl_gross"] = df["funding_pnl"]
    df["pnl_net"] = df["funding_pnl"] - df["fees_paid"]
    df["equity_gross"] = df["pnl_gross"].cumsum()
    df["equity_net"] = df["pnl_net"].cumsum()

    trade_rows = []
    for t in trades:
        entry_t = df["timestamp"].iloc[t["entry_idx"]]
        exit_t = df["timestamp"].iloc[t["exit_idx"]] if t["exit_idx"] is not None else pd.NaT
        trade_rows.append(
            {
                "entry_time": entry_t,
                "exit_time": exit_t,
                "side": t["side"],
                "hours_held": t["hours_held"],
                "exit_reason": t["exit_reason"],
            }
        )
    trades_df = pd.DataFrame(trade_rows)

    return {
        "df": df,
        "trades": trades_df,
        "costs": costs,
        "cfg": cfg,
        "breakeven_annualized": be,
        "entry_threshold_annualized": entry_threshold,
    }


def run_single_asset_backtest(
    raw_df: pd.DataFrame,
    costs: CostAssumptions,
    cfg: StrategyConfig,
    sizer: Optional[Sizer] = None,
) -> dict:
    df = add_annualized_rate(raw_df)
    return generate_positions_and_backtest(df, costs, cfg, sizer=sizer)


# ---------------------------------------------------------------------------
# 5. ROTATION VARIANT -- single capital pool rotated across BTC/ETH/SOL
# ---------------------------------------------------------------------------

def build_aligned_panel(raw_dfs: dict[str, pd.DataFrame], tolerance_minutes: float = 15.0) -> pd.DataFrame:
    """Align the per-coin annualized-rate series onto the first coin's
    timeline via nearest-match within `tolerance_minutes` (funding events
    across coins land within a few hundred ms of each other once hourly
    settlement starts; before that, an 8h cadence, still shared). All three
    of BTC/ETH/SOL are confirmed to share an identical cadence and listing
    date on Hyperliquid, so this does not drop any real data in practice;
    rows are still checked and dropped below if any coin is missing data."""
    prepared = {c: add_annualized_rate(df).sort_values("timestamp") for c, df in raw_dfs.items()}
    coins = list(prepared)
    common_ts = prepared[coins[0]][["timestamp"]].drop_duplicates().sort_values("timestamp").reset_index(drop=True)

    panel = common_ts.copy()
    for c in coins:
        merged = pd.merge_asof(
            common_ts,
            prepared[c][["timestamp", "fundingRate", "annualized_rate", "period_hours"]].sort_values("timestamp"),
            on="timestamp",
            direction="nearest",
            tolerance=pd.Timedelta(minutes=tolerance_minutes),
        )
        panel[f"fundingRate_{c}"] = merged["fundingRate"]
        panel[f"annualized_rate_{c}"] = merged["annualized_rate"]
        panel[f"period_hours_{c}"] = merged["period_hours"]

    # Only keep rows where every coin has data (all three listed & reporting).
    rate_cols = [f"annualized_rate_{c}" for c in coins]
    panel = panel.dropna(subset=rate_cols).reset_index(drop=True)
    return panel


def run_rotation_backtest(
    raw_dfs: dict[str, pd.DataFrame],
    costs: CostAssumptions,
    cfg: StrategyConfig,
    sizer: Optional[Sizer] = None,
    switch_margin_ratio: float = 1.2,
) -> dict:
    """Rotate a single capital pool into whichever of BTC/ETH/SOL currently
    clears breakeven by the widest margin. `switch_margin_ratio` requires a
    challenger asset's margin to exceed the currently-held asset's margin by
    this ratio before rotating, as hysteresis against fee-churning on noise
    (a rotation still costs a full round trip like any other exit+entry)."""
    sizer = sizer or fixed_notional_sizer(cfg.notional)
    coins = list(raw_dfs)
    panel = build_aligned_panel(raw_dfs)
    be = breakeven_annualized_rate(costs, cfg.breakeven_horizon_hours)
    entry_threshold = cfg.buffer_multiplier * be

    n = len(panel)
    rate_mat = {c: panel[f"annualized_rate_{c}"].to_numpy() for c in coins}
    period_mat = {c: panel[f"period_hours_{c}"].to_numpy() for c in coins}
    fund_mat = {c: panel[f"fundingRate_{c}"].to_numpy() for c in coins}

    held_coin = np.array([None] * n, dtype=object)
    side = np.zeros(n, dtype=int)
    is_entry = np.zeros(n, dtype=bool)
    is_exit = np.zeros(n, dtype=bool)
    traded_coin_at_i = np.array([None] * n, dtype=object)  # coin an entry/exit fee applies to

    trades: list[dict] = []
    cur_coin: Optional[str] = None
    cur_side = 0
    cur_hours = 0.0
    entry_idx: Optional[int] = None

    def margin(c: str, i: int) -> float:
        return abs(rate_mat[c][i]) - be

    for i in range(n):
        if cur_coin is not None:
            cur_hours += period_mat[cur_coin][i]

        candidates = [c for c in coins if abs(rate_mat[c][i]) > entry_threshold]

        if cur_coin is None:
            if candidates:
                best = max(candidates, key=lambda c: margin(c, i))
                cur_coin = best
                cur_side = 1 if rate_mat[best][i] > 0 else -1
                cur_hours = 0.0
                entry_idx = i
                is_entry[i] = True
                traded_coin_at_i[i] = best
        else:
            r_cur = rate_mat[cur_coin][i]
            cur_sign = 1 if r_cur > 0 else (-1 if r_cur < 0 else 0)
            flipped = cur_sign != 0 and cur_sign != cur_side
            below_be = abs(r_cur) < be
            maxed_out = cfg.max_holding_hours is not None and cur_hours >= cfg.max_holding_hours

            challenger = None
            if not (flipped or below_be or maxed_out):
                others = [c for c in candidates if c != cur_coin]
                if others:
                    best_other = max(others, key=lambda c: margin(c, i))
                    cur_margin = margin(cur_coin, i)
                    if cur_margin <= 0 or margin(best_other, i) >= switch_margin_ratio * max(cur_margin, 1e-12):
                        challenger = best_other

            if flipped or below_be or maxed_out or challenger is not None:
                is_exit[i] = True
                traded_coin_at_i[i] = cur_coin
                trades.append(
                    {
                        "coin": cur_coin,
                        "entry_idx": entry_idx,
                        "exit_idx": i,
                        "side": cur_side,
                        "hours_held": cur_hours,
                        "exit_reason": (
                            "flip" if flipped else "max_holding" if maxed_out else
                            "below_breakeven" if below_be else "rotated"
                        ),
                    }
                )
                prev_coin_traded = cur_coin
                cur_coin, cur_side, cur_hours, entry_idx = None, 0, 0.0, None

                next_pick = None
                if flipped and abs(r_cur) > entry_threshold:
                    next_pick = prev_coin_traded
                elif challenger is not None:
                    next_pick = challenger
                if next_pick is not None:
                    cur_coin = next_pick
                    cur_side = 1 if rate_mat[next_pick][i] > 0 else -1
                    cur_hours = 0.0
                    entry_idx = i
                    is_entry[i] = True
                    # both an exit and entry fee this row; entry may be on a
                    # different coin than the exit, tracked separately below
                    if next_pick != prev_coin_traded:
                        traded_coin_at_i[i] = (prev_coin_traded, next_pick)
                    else:
                        traded_coin_at_i[i] = prev_coin_traded

        held_coin[i] = cur_coin
        side[i] = cur_side

    if cur_coin is not None and entry_idx is not None:
        trades.append(
            {
                "coin": cur_coin,
                "entry_idx": entry_idx,
                "exit_idx": None,
                "side": cur_side,
                "hours_held": cur_hours,
                "exit_reason": "open_at_end_of_data",
            }
        )

    panel = panel.copy()
    panel["held_coin"] = held_coin
    panel["side"] = side
    panel["is_entry"] = is_entry
    panel["is_exit"] = is_exit
    panel["notional"] = panel.apply(sizer, axis=1)

    held_coin_prev = pd.Series(held_coin).shift(1)
    side_prev = pd.Series(side).shift(1).fillna(0).astype(int)
    funding_pnl = np.zeros(n)
    for i in range(n):
        hc = held_coin_prev.iloc[i]
        if hc is not None and isinstance(hc, str):
            funding_pnl[i] = side_prev.iloc[i] * fund_mat[hc][i] * panel["notional"].iloc[i]
    panel["held_side"] = side_prev.to_numpy()
    panel["funding_pnl"] = funding_pnl

    one_way_frac = costs.one_way_cost_bps() / 1e4
    n_fills = np.zeros(n, dtype=int)
    for i in range(n):
        tc = traded_coin_at_i[i]
        if tc is None:
            continue
        n_fills[i] = 2 if isinstance(tc, tuple) else 1
    panel["fees_paid"] = n_fills * panel["notional"] * one_way_frac

    panel["pnl_gross"] = panel["funding_pnl"]
    panel["pnl_net"] = panel["funding_pnl"] - panel["fees_paid"]
    panel["equity_gross"] = panel["pnl_gross"].cumsum()
    panel["equity_net"] = panel["pnl_net"].cumsum()

    trade_rows = []
    for t in trades:
        entry_t = panel["timestamp"].iloc[t["entry_idx"]]
        exit_t = panel["timestamp"].iloc[t["exit_idx"]] if t["exit_idx"] is not None else pd.NaT
        trade_rows.append(
            {
                "coin": t["coin"],
                "entry_time": entry_t,
                "exit_time": exit_t,
                "side": t["side"],
                "hours_held": t["hours_held"],
                "exit_reason": t["exit_reason"],
            }
        )
    trades_df = pd.DataFrame(trade_rows)

    return {
        "df": panel,
        "trades": trades_df,
        "costs": costs,
        "cfg": cfg,
        "breakeven_annualized": be,
        "entry_threshold_annualized": entry_threshold,
    }


# ---------------------------------------------------------------------------
# 6. METRICS / LIQUIDITY FLAGS
# ---------------------------------------------------------------------------

def compute_metrics(result: dict, periods_per_year: float = HOURS_PER_YEAR) -> dict:
    df = result["df"]
    trades = result["trades"]
    notional = df["notional"].replace(0, np.nan)

    ret_net = (df["pnl_net"] / notional).fillna(0.0)
    ret_gross = (df["pnl_gross"] / notional).fillna(0.0)

    n_hours = len(df)
    years = n_hours / periods_per_year if n_hours else np.nan

    total_return_net = ret_net.sum()
    total_return_gross = ret_gross.sum()
    # Simple (non-compounding) annualization: appropriate for a fixed-notional,
    # cash-funding-collecting strategy where P&L is additive, not reinvested.
    ann_return_net = total_return_net / years if years else np.nan
    ann_return_gross = total_return_gross / years if years else np.nan

    sharpe_net = (
        ret_net.mean() / ret_net.std(ddof=1) * math.sqrt(periods_per_year)
        if ret_net.std(ddof=1) > 0 else np.nan
    )

    cum_net = ret_net.cumsum()
    running_max = cum_net.cummax()
    drawdown = cum_net - running_max
    max_dd_net = drawdown.min() if len(drawdown) else np.nan

    pct_hours_in_position = float((df["held_side"] != 0).mean()) if "held_side" in df else np.nan
    n_trades = len(trades)
    avg_holding_hours = float(trades["hours_held"].mean()) if n_trades else np.nan
    total_fees_frac = (df["fees_paid"] / notional).fillna(0.0).sum()

    return {
        "n_hours": n_hours,
        "years": years,
        "total_return_gross": total_return_gross,
        "total_return_net": total_return_net,
        "annualized_return_gross": ann_return_gross,
        "annualized_return_net": ann_return_net,
        "sharpe_net": sharpe_net,
        "max_drawdown_net": max_dd_net,
        "pct_hours_in_position": pct_hours_in_position,
        "n_trades": n_trades,
        "avg_holding_hours": avg_holding_hours,
        "total_fee_drag_frac": total_fees_frac,
    }


def flag_illiquidity_periods(
    raw_df: pd.DataFrame, min_run_hours: float = 24 * 14
) -> pd.DataFrame:
    """Find runs where the raw funding-rate sign stays constant for longer
    than `min_run_hours`. A funding rate that persists one-directionally for
    weeks is exactly the situation where, in reality, enough capital would
    already have piled onto the profitable side to compress the rate (or the
    move itself reflects a supply/demand imbalance too large to enter/exit
    at meaningful size without moving the rate against you). This backtest
    assumes fills at the historical rate/notional with no market impact, so
    it will overstate returns during any period flagged here."""
    df = add_annualized_rate(raw_df)
    sign = np.sign(df["fundingRate"].to_numpy())
    n = len(sign)
    runs = []
    start = 0
    for i in range(1, n + 1):
        if i == n or sign[i] != sign[start]:
            run_hours = float(df["time"].iloc[i - 1] - df["time"].iloc[start]) / 3_600_000.0
            if run_hours >= min_run_hours and sign[start] != 0:
                runs.append(
                    {
                        "start": df["timestamp"].iloc[start],
                        "end": df["timestamp"].iloc[i - 1],
                        "direction": "positive" if sign[start] > 0 else "negative",
                        "run_hours": run_hours,
                        "run_days": run_hours / 24.0,
                        "mean_annualized_rate": float(df["annualized_rate"].iloc[start:i].mean()),
                    }
                )
            start = i
    return pd.DataFrame(runs)


# ---------------------------------------------------------------------------
# 7. PLOTS / SUMMARY TABLE / REPORT
# ---------------------------------------------------------------------------

def _df_to_markdown(df: pd.DataFrame, float_fmt: str = "{:.4f}") -> str:
    """Minimal markdown-table formatter (avoids adding a `tabulate` dep)."""
    if df.empty:
        return "_(none)_"

    def fmt(v):
        if isinstance(v, float):
            return float_fmt.format(v)
        return str(v)

    cols = list(df.columns)
    header = "| " + " | ".join(cols) + " |"
    sep = "| " + " | ".join("---" for _ in cols) + " |"
    body = "\n".join(
        "| " + " | ".join(fmt(v) for v in row) + " |" for row in df.itertuples(index=False)
    )
    return "\n".join([header, sep, body])

def plot_cumulative_returns(result: dict, title: str, out_path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    df = result["df"]
    notional = df["notional"].replace(0, np.nan)
    cum_gross = (df["pnl_gross"] / notional).fillna(0.0).cumsum()
    cum_net = (df["pnl_net"] / notional).fillna(0.0).cumsum()

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(df["timestamp"], cum_gross * 100, label="Gross of fees", linewidth=1.3)
    ax.plot(df["timestamp"], cum_net * 100, label="Net of fees", linewidth=1.3)
    ax.set_title(title)
    ax.set_xlabel("Date")
    ax.set_ylabel("Cumulative return (%)")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def build_summary_table(all_metrics: dict[tuple, dict]) -> pd.DataFrame:
    rows = []
    for (label, fill_type, holding_variant), m in all_metrics.items():
        row = {"asset_or_variant": label, "fill_type": fill_type, "holding_variant": holding_variant}
        row.update(m)
        rows.append(row)
    return pd.DataFrame(rows)


def write_report(
    summary_df: pd.DataFrame,
    illiquidity_flags: dict[str, pd.DataFrame],
    costs_maker: CostAssumptions,
    costs_taker: CostAssumptions,
    cfg_base: StrategyConfig,
    out_path: Path,
) -> None:
    lines = []
    lines.append("# Hyperliquid Spot-Perp Funding Arbitrage Backtest -- Report\n")
    lines.append(
        "Data source: Hyperliquid public `/info` `fundingHistory` endpoint "
        "(no auth). Full history pulled for BTC, ETH, SOL from each asset's "
        "first available record through the run time; all three coins first "
        "report funding on 2023-05-12 (their Hyperliquid listing date).\n"
    )
    lines.append(
        "**Funding cadence data quirk**: Hyperliquid funding settled every "
        "8 hours from 2023-05-12 until ~2023-06-08, then switched to hourly "
        "settlement (confirmed by inspecting the gap between consecutive "
        "raw records, not assumed). This pipeline derives the settlement "
        "cadence from the actual timestamp gaps at each point and "
        "annualizes off that, so it is correct across the regime switch "
        "without hardcoding either convention.\n"
    )
    lines.append(
        f"**Fees** (Hyperliquid Tier 0, confirmed against the docs on "
        f"2026-08-25): perp maker {costs_maker.fees.perp_maker_bps/100:.3f}% / "
        f"taker {costs_maker.fees.perp_taker_bps/100:.3f}%, spot maker "
        f"{costs_maker.fees.spot_maker_bps/100:.3f}% / taker "
        f"{costs_maker.fees.spot_taker_bps/100:.3f}%. Slippage assumed at "
        f"{costs_maker.slippage_bps_per_leg:.1f} bps per leg (configurable).\n"
    )
    be_maker = breakeven_annualized_rate(costs_maker, cfg_base.breakeven_horizon_hours)
    be_taker = breakeven_annualized_rate(costs_taker, cfg_base.breakeven_horizon_hours)
    lines.append(
        f"**Breakeven derivation**: round-trip cost = 2 x (spot fee + perp "
        f"fee + 2 x slippage per leg). Amortized over a "
        f"{cfg_base.breakeven_horizon_hours:.0f}h assumed minimum holding "
        f"horizon (configurable) to get a breakeven *hourly* rate, then "
        f"annualized (x{HOURS_PER_YEAR}). Maker-fill breakeven: "
        f"{be_maker*100:.2f}% annualized. Taker-fill breakeven: "
        f"{be_taker*100:.2f}% annualized. Entry requires the observed "
        f"annualized funding rate to exceed "
        f"{cfg_base.buffer_multiplier:.1f}x breakeven (configurable buffer).\n"
    )
    lines.append("## Results summary\n")
    lines.append(_df_to_markdown(summary_df))
    lines.append("\n")

    lines.append("## Illiquidity / persistence flags\n")
    lines.append(
        "Runs where the raw hourly funding rate stayed one-directional for "
        "2+ weeks. Real capital would likely have compressed a rate that "
        "persisted this long, or the imbalance itself reflects limited "
        "liquidity at size -- this backtest assumes fills at the historical "
        "rate/notional with zero market impact, so returns during these "
        "windows are probably overstated.\n"
    )
    for coin, flags in illiquidity_flags.items():
        lines.append(f"\n**{coin}**\n")
        if flags.empty:
            lines.append("No runs exceeding the threshold.\n")
        else:
            lines.append(_df_to_markdown(flags))
            lines.append("\n")

    lines.append("\n## Caveats\n")
    lines.append(
        "- Ignores basis/premium P&L from the spot-perp price convergence; "
        "assumes a perfectly delta-neutral hedge, only the funding "
        "differential is modeled.\n"
        "- The 'reverse when funding is negative' leg (short spot / long "
        "perp) assumes short-spot exposure is available at the modeled spot "
        "fee with no separate borrow cost -- Hyperliquid spot itself has no "
        "native margin/short, so in practice this leg needs a borrow "
        "facility whose cost is not modeled here.\n"
        "- No market impact / depth modeling: fills assumed at the "
        "historical funding rate and full requested notional regardless of "
        "size.\n"
        "- The volatility-adjusted sizer (see `vol_adjusted_sizer`) is "
        "illustrative only, using trailing volatility of the funding "
        "signal itself as a proxy since this pipeline does not fetch spot "
        "price history.\n"
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines))


# ---------------------------------------------------------------------------
# 8. MAIN
# ---------------------------------------------------------------------------

def main() -> None:
    print("Fetching / loading cached Hyperliquid funding history for", COINS)
    raw: dict[str, pd.DataFrame] = {}
    for coin in COINS:
        raw[coin] = fetch_full_funding_history(coin)
        span_days = (raw[coin]["time"].iloc[-1] - raw[coin]["time"].iloc[0]) / 86_400_000
        print(f"  {coin}: {len(raw[coin])} records, "
              f"{raw[coin]['timestamp'].iloc[0].date()} -> {raw[coin]['timestamp'].iloc[-1].date()} "
              f"(~{span_days:.0f} days)")

    cfg_uncapped = StrategyConfig(buffer_multiplier=2.0, breakeven_horizon_hours=24.0, max_holding_hours=None)
    # Observed trade durations in this dataset top out around 50-60h (funding
    # spikes tend to mean-revert quickly), so a 7-day cap never binds -- a
    # 24h cap is the tighter, more informative comparison point.
    cfg_capped = replace(cfg_uncapped, max_holding_hours=24.0)

    holding_variants = [("uncapped", cfg_uncapped), ("capped_24h", cfg_capped)]

    costs_by_fill = {
        "maker": CostAssumptions(fill_type="maker", slippage_bps_per_leg=2.0),
        "taker": CostAssumptions(fill_type="taker", slippage_bps_per_leg=2.0),
    }

    all_results: dict[tuple, dict] = {}
    all_metrics: dict[tuple, dict] = {}

    for fill_type, costs in costs_by_fill.items():
        for holding_label, cfg in holding_variants:
            for coin in COINS:
                res = run_single_asset_backtest(raw[coin], costs, cfg)
                key = (coin, fill_type, holding_label)
                all_results[key] = res
                all_metrics[key] = compute_metrics(res)

            rot_res = run_rotation_backtest(raw, costs, cfg)
            key = ("ROTATION", fill_type, holding_label)
            all_results[key] = rot_res
            all_metrics[key] = compute_metrics(rot_res)

    summary_df = build_summary_table(all_metrics)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    summary_df.to_csv(RESULTS_DIR / "summary_metrics.csv", index=False)
    print("\n=== Summary (all fee / holding-period variants) ===")
    with pd.option_context("display.max_columns", None, "display.width", 200):
        print(summary_df.to_string(index=False))

    # Headline plots: maker fees, uncapped holding (the base-case scenario).
    for label in COINS + ["ROTATION"]:
        res = all_results[(label, "maker", "uncapped")]
        plot_cumulative_returns(
            res,
            f"{label}: cumulative return, gross vs net of fees (maker fills, no holding cap)",
            PLOTS_DIR / f"{label.lower()}_cumulative_return.png",
        )
    print(f"\nPlots written to {PLOTS_DIR}")

    illiquidity_flags = {coin: flag_illiquidity_periods(raw[coin]) for coin in COINS}

    write_report(
        summary_df=summary_df,
        illiquidity_flags=illiquidity_flags,
        costs_maker=costs_by_fill["maker"],
        costs_taker=costs_by_fill["taker"],
        cfg_base=cfg_uncapped,
        out_path=RESULTS_DIR / "report.md",
    )
    print(f"Report written to {RESULTS_DIR / 'report.md'}")


if __name__ == "__main__":
    main()
