"""Diagnostic: does EGARCH's beta[1] hit the arch package's [0,1] box
constraint (pinned near/at 1.0) systematically, and if so, is that a data
problem (regime-specific), a specification problem (this EGARCH order
doesn't fit certain periods), or a window-length problem?

Not part of the pipeline. Reuses the exact same arch_model call as
walk_forward.py's production loop (same distribution, same min_obs, same
daily refit) but logs beta_raw for EVERY window, not just aggregated
accept/reject counts.

Run as: PYTHONPATH=src python3 scripts/audit_beta_pinning.py
"""

from __future__ import annotations

import sys
import time

sys.path.insert(0, "src")

import numpy as np
import pandas as pd
from arch import arch_model
from scipy import stats as spstats

from spx_egarch_gex import config
from spx_egarch_gex.models.egarch import RETURN_SCALE
from spx_egarch_gex.models.walk_forward import MAX_ABS_BETA, _forecast_sane, _params_sane

DIST = "skewt"
MIN_OBS = 500
PIN_THRESHOLD = 0.9999  # "truly pinned" vs merely high-persistence


def instrumented_expanding_walk_forward(returns: pd.Series) -> pd.DataFrame:
    r = (returns.dropna() * RETURN_SCALE).astype(float)
    dates = r.index
    n = len(r)

    rows = []
    for t in range(MIN_OBS, n):
        train = r.iloc[0:t]  # expanding window, strictly before t
        am = arch_model(train, mean="Constant", vol="EGARCH", p=1, o=1, q=1, dist=DIST)
        res = am.fit(disp="off", show_warning=False)
        params = res.params
        beta = float(params.get("beta[1]", np.nan))
        fc = res.forecast(horizon=1, reindex=False)
        var_pct2 = fc.variance.iloc[-1, 0]

        accepted = _params_sane(params) and _forecast_sane(var_pct2)
        rows.append({
            "date": dates[t],
            "window_start": dates[0],
            "window_end": dates[t - 1],
            "window_length": t,
            "beta": beta,
            "pinned": beta >= PIN_THRESHOLD,
            "accepted": accepted,
            "convergence_flag": int(res.convergence_flag),
        })

    return pd.DataFrame(rows)


def window_length_sensitivity(returns: pd.Series, pinned_dates: pd.DatetimeIndex,
                               lengths=(250, 500, 1000, 2000, 3000)) -> pd.DataFrame:
    r = (returns.dropna() * RETURN_SCALE).astype(float)
    dates = r.index
    rows = []
    for d in pinned_dates:
        t = dates.get_loc(d)
        for L in lengths:
            lo = max(0, t - L)
            if t - lo < 100:  # not enough data for this length at this date
                continue
            train = r.iloc[lo:t]
            am = arch_model(train, mean="Constant", vol="EGARCH", p=1, o=1, q=1, dist=DIST)
            try:
                res = am.fit(disp="off", show_warning=False)
                beta = float(res.params.get("beta[1]", np.nan))
            except Exception:
                beta = np.nan
            rows.append({"date": d, "window_length_requested": L, "actual_length": t - lo,
                        "beta": beta, "pinned": beta >= PIN_THRESHOLD})
    return pd.DataFrame(rows)


def clustering_test(log: pd.DataFrame) -> str:
    log = log.copy()
    log["year"] = log["date"].dt.year
    by_year = log.groupby("year").agg(n_windows=("pinned", "size"), n_pinned=("pinned", "sum"))
    by_year["pin_rate"] = by_year["n_pinned"] / by_year["n_windows"]

    total_windows = by_year["n_windows"].sum()
    total_pinned = by_year["n_pinned"].sum()
    overall_rate = total_pinned / total_windows

    # chi-square goodness-of-fit: observed pins per year vs expected under
    # uniform pin-rate across all eligible windows (proportional to each
    # year's window count)
    expected = by_year["n_windows"] * overall_rate
    # merge sparse years to keep expected counts reasonable for chi-square validity
    valid = expected >= 1
    obs = by_year.loc[valid, "n_pinned"]
    exp = expected[valid]
    exp = exp * (obs.sum() / exp.sum())  # rescale: chisquare requires sum(obs)==sum(exp) exactly;
    # dropping sparse years unavoidably desyncs the totals, so rescale the
    # kept-years' expected counts to preserve their relative shape (still
    # driven by each year's own window count) while matching sum(obs).
    chi2, pval = spstats.chisquare(obs, exp)

    lines = []
    lines.append(f"Overall pin rate: {total_pinned}/{total_windows} = {overall_rate:.4%}")
    lines.append("")
    lines.append("Pin rate by year:")
    lines.append(by_year.to_string())
    lines.append("")
    lines.append(f"Chi-square test (observed pins/year vs uniform-rate expectation): "
                f"chi2={chi2:.2f}  p={pval:.2e}")
    lines.append("(p << 0.05 => pinning is NOT uniformly scattered across years; "
                "it is clustered in specific periods)" if pval < 0.05 else
                "(p >= 0.05 => cannot reject uniform scattering across years)")
    top_years = by_year.sort_values("pin_rate", ascending=False).head(5)
    lines.append("")
    lines.append("Top-5 years by pin rate:")
    lines.append(top_years.to_string())
    return "\n".join(lines)


def main():
    panel = pd.read_csv(config.PROCESSED_DIR / "panel.csv", index_col="date", parse_dates=["date"])
    returns = panel["spx_log_ret"].dropna()

    print(f"Instrumented expanding-window walk-forward: {returns.index.min().date()} -> "
        f"{returns.index.max().date()}  dist={DIST}  min_obs={MIN_OBS}")
    t0 = time.time()
    log = instrumented_expanding_walk_forward(returns)
    print(f"done in {time.time()-t0:.1f}s,  n_windows={len(log)}")

    log.to_csv(config.PROCESSED_DIR / "egarch_beta_pinning_log.csv", index=False)
    print(f"wrote per-window log to data/processed/egarch_beta_pinning_log.csv")

    report_lines = []
    report_lines.append("=== Beta boundary-pinning diagnostic (expanding window, daily refit) ===")
    report_lines.append(f"pin threshold: beta >= {PIN_THRESHOLD}")
    report_lines.append("")

    report_lines.append(clustering_test(log))
    report_lines.append("")

    pinned_dates = log.loc[log["pinned"], "date"]
    report_lines.append(f"Total pinned windows: {len(pinned_dates)}")
    if len(pinned_dates):
        report_lines.append(f"First pinned date: {pinned_dates.min().date()}   Last pinned date: {pinned_dates.max().date()}")
        contiguous_years = sorted(pinned_dates.dt.year.unique())
        report_lines.append(f"Years with >=1 pinned window: {contiguous_years}")

    report_lines.append("")
    report_lines.append("=== Window-length sensitivity on pinned dates ===")
    if len(pinned_dates):
        n_sample = min(40, len(pinned_dates))
        rng = np.random.default_rng(0)
        sample_dates = pd.DatetimeIndex(rng.choice(pinned_dates.to_numpy(), size=n_sample, replace=False))
        sens = window_length_sensitivity(returns, sample_dates)
        sens.to_csv(config.PROCESSED_DIR / "egarch_beta_pinning_length_sensitivity.csv", index=False)
        pivot = sens.pivot_table(index="date", columns="window_length_requested", values="pinned")
        report_lines.append(f"Sampled {n_sample} pinned dates, refit at lengths {sorted(sens['window_length_requested'].unique())}:")
        report_lines.append(pivot.to_string())
        report_lines.append("")
        pin_rate_by_length = sens.groupby("window_length_requested")["pinned"].mean()
        report_lines.append("Pin rate by window length (across the sampled pinned dates):")
        report_lines.append(pin_rate_by_length.to_string())
    else:
        report_lines.append("No pinned windows found -- skipping.")

    report = "\n".join(report_lines)
    print(report)
    out_path = config.RESULTS_DIR / "egarch_beta_pinning_audit.txt"
    out_path.write_text(report + "\n")
    print(f"\nWrote report to {out_path}")


if __name__ == "__main__":
    main()
