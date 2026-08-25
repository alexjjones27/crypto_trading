"""Build the merged daily panel (SPX, VIX, GEX/DIX) and print a data report.

Run as: python -m spx_egarch_gex.data.build_dataset
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from spx_egarch_gex import config
from spx_egarch_gex.data.gex import fetch_and_cache_gex
from spx_egarch_gex.data.yahoo import fetch_spx, fetch_vix

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def build_panel(refresh: bool = False) -> pd.DataFrame:
    spx = fetch_spx(start=config.EGARCH_DIAGNOSTIC_START, refresh=refresh)
    vix = fetch_vix(start=config.EGARCH_DIAGNOSTIC_START, refresh=refresh)
    gex = fetch_and_cache_gex(refresh=refresh)

    panel = pd.DataFrame(index=spx.index)
    panel["spx_close"] = spx["Close"]
    panel["spx_log_ret"] = np.log(panel["spx_close"]).diff()
    panel["vix_close"] = vix["Close"]
    panel["dix"] = gex["dix"]
    panel["gex"] = gex["gex"]
    panel["gex_price"] = gex["price"]  # SqueezeMetrics' own SPX close, for cross-check

    panel = panel.sort_index()
    panel.to_csv(config.PROCESSED_DIR / "panel.csv")
    return panel


def data_report(panel: pd.DataFrame) -> str:
    lines = []
    lines.append("=== Data coverage ===")
    for col in ["spx_close", "vix_close", "gex", "dix"]:
        s = panel[col].dropna()
        lines.append(f"{col:12s}: {s.index.min().date()} -> {s.index.max().date()}  n={len(s)}")

    lines.append("")
    lines.append("=== GEX-constrained window ===")
    gex_start = panel["gex"].dropna().index.min()
    lines.append(f"First usable GEX date: {gex_start.date()}")
    n_full = panel.loc[gex_start:].dropna(subset=["spx_close", "vix_close", "gex"])
    lines.append(f"Rows with all of spx/vix/gex present from {gex_start.date()}: {len(n_full)}")

    lines.append("")
    lines.append("=== Missingness within GEX-covered window ===")
    sub = panel.loc[gex_start:]
    for col in ["spx_close", "vix_close", "gex", "dix"]:
        miss = sub[col].isna().sum()
        lines.append(f"{col:12s}: {miss} missing / {len(sub)} rows ({miss / len(sub):.2%})")

    lines.append("")
    lines.append("=== Trading-day alignment check (SPX close vs SqueezeMetrics' own price) ===")
    both = sub.dropna(subset=["spx_close", "gex_price"])
    diff = (both["spx_close"] - both["gex_price"]).abs()
    rel_diff = diff / both["spx_close"]
    lines.append(f"Max abs price diff: {diff.max():.4f} ({rel_diff.max():.4%} relative)")
    lines.append(f"Mean abs price diff: {diff.mean():.4f} ({rel_diff.mean():.4%} relative)")
    n_mismatch = (rel_diff > 0.001).sum()
    lines.append(f"Rows with >0.1% price mismatch (possible date misalignment): {n_mismatch}")

    lines.append("")
    lines.append("=== Proposed split (see config.py; PENDING CONFIRMATION) ===")
    for name, (s, e) in [
        ("in-sample", config.SPLIT_IN_SAMPLE),
        ("validation", config.SPLIT_VALIDATION),
        ("holdout", config.SPLIT_HOLDOUT),
    ]:
        e_eff = e or panel.index.max().date().isoformat()
        seg = panel.loc[s:e_eff]
        seg_full = seg.dropna(subset=["spx_close", "vix_close", "gex"])
        lines.append(f"{name:11s}: {s} -> {e_eff}  ({len(seg_full)} complete rows)")

    return "\n".join(lines)


if __name__ == "__main__":
    panel = build_panel(refresh=False)
    report = data_report(panel)
    print(report)
    with open(config.RESULTS_DIR / "checkpoint1_data_report.txt", "w") as f:
        f.write(report + "\n")
