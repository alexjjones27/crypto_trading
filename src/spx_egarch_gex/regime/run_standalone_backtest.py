"""Checkpoint 3: standalone validation of the dealer-gamma regime signal.

Answers, before the regime signal is combined with anything else:
  1. Is the GEX value for date T knowable in real time at T's decision
     point, or published with a lag? (determines whether this signal is
     tradeable at all without look-ahead bias)
  2. Does the positive-gamma regime actually show lower realized vol?
  3. Does the positive-gamma regime actually show more mean-reverting
     price action (negative return autocorrelation), and negative-gamma
     more trending (positive autocorrelation)?

Run as: python -m spx_egarch_gex.regime.run_standalone_backtest
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from spx_egarch_gex import config
from spx_egarch_gex.regime.classifier import classify_regime_sign, lag_for_trading
from spx_egarch_gex.stats.inference import circular_shift_permutation_test

REALTIME_AVAILABILITY_NOTE = """\
=== Real-time availability of the GEX signal ===

SqueezeMetrics' free DIX/GEX CSV (squeezemetrics.com/monitor/static/DIX.csv)
is computed from that trading day's end-of-day dark-pool/options data, i.e.
each row labeled date T reflects information only fully observable after
T's close. We did NOT have access to a historical log of exact publish
timestamps (no way to retroactively confirm, e.g., "row T appeared on the
site at HH:MM on day T+1"). What we DID confirm directly: fetching the CSV
on 2026-08-25 (a trading day) returned a last row dated 2026-08-24 (the
prior close) -- consistent with same-evening-after-close or next-morning
publication, i.e. a ~1-trading-day lag, and NOT same-day intraday
availability.

Working assumption used throughout this backtest (stated explicitly
because it is load-bearing): GEX_T becomes usable for a trading decision
made at T+1's open at the earliest -- i.e. a full 1-trading-day lag between
the date a GEX row describes and the date it can inform a trade. This is
enforced everywhere below via `lag_for_trading(regime, lag=1)`: the regime
label driving day t's analysis is always built from GEX_{t-1}, never
GEX_t. A lag=2 variant is also reported as a robustness check in case the
true publish lag is longer than assumed (e.g. if the free tier is delayed
an extra day relative to the paid feed) -- if the standalone result
survives lag=2, the conclusion isn't fragile to getting the exact lag
slightly wrong. It is NOT survivable if the true lag turns out to be
*shorter* than we assume (that would only make our backtest more
conservative, not less), but if it turns out GEX_T is NOT usable until
T+2 or later, lag=1 results would themselves be look-ahead-biased --
flagged here as the key unverified assumption in this checkpoint.
"""


def variance_ratio_simple(r: np.ndarray, q: int) -> float:
    n = len(r)
    var_1 = r.var(ddof=1)
    r_q = pd.Series(r).rolling(q).sum().dropna().to_numpy()
    if len(r_q) < 2 or var_1 <= 0:
        return np.nan
    var_q = r_q.var(ddof=1)
    return var_q / (q * var_1)


def find_runs(labels: pd.Series) -> list[tuple[str, pd.Timestamp, pd.Timestamp]]:
    runs = []
    labels = labels.dropna()
    if labels.empty:
        return runs
    start = labels.index[0]
    cur = labels.iloc[0]
    prev_idx = start
    for idx, val in labels.iloc[1:].items():
        if val != cur:
            runs.append((cur, start, prev_idx))
            start = idx
            cur = val
        prev_idx = idx
    runs.append((cur, start, prev_idx))
    return runs


def regime_variance_ratios(returns: pd.Series, labels: pd.Series, q: int, min_run: int) -> dict:
    runs = find_runs(labels)
    vrs = {"positive": [], "negative": []}
    for label, start, end in runs:
        if label not in vrs:
            continue
        seg = returns.loc[start:end].dropna()
        if len(seg) < min_run:
            continue
        vr = variance_ratio_simple(seg.to_numpy(), q)
        if np.isfinite(vr):
            vrs[label].append((vr, len(seg)))
    out = {}
    for label, lst in vrs.items():
        if not lst:
            out[label] = {"vr_mean": np.nan, "n_runs": 0, "total_days": 0}
            continue
        vr_vals = np.array([v for v, _ in lst])
        weights = np.array([w for _, w in lst])
        out[label] = {
            "vr_mean": float(np.average(vr_vals, weights=weights)),
            "vr_median": float(np.median(vr_vals)),
            "n_runs": len(lst),
            "total_days": int(weights.sum()),
        }
    return out


def diff_mean_abs_ret(labels: pd.Series, values: pd.Series) -> float:
    pos = values[labels == "positive"]
    neg = values[labels == "negative"]
    return float(pos.mean() - neg.mean())


def diff_std_ret(labels: pd.Series, values: pd.Series) -> float:
    pos = values[labels == "positive"]
    neg = values[labels == "negative"]
    return float(pos.std() - neg.std())


def autocorr_diff_stat(df: pd.DataFrame, label_col: pd.Series) -> float:
    pos = df.loc[label_col == "positive"]
    neg = df.loc[label_col == "negative"]
    if len(pos) < 30 or len(neg) < 30:
        return np.nan
    return float(pos["r"].corr(pos["r_lag"]) - neg["r"].corr(neg["r_lag"]))


def circular_shift_autocorr_test(df: pd.DataFrame, n_perm: int = 2000, random_state: int = 0) -> dict:
    n = len(df)
    observed = autocorr_diff_stat(df, df["label"])
    rng = np.random.default_rng(random_state)
    label_arr = df["label"].to_numpy()
    null_stats = np.empty(n_perm)
    for i in range(n_perm):
        shift = rng.integers(1, n)
        shifted = pd.Series(np.roll(label_arr, shift), index=df.index)
        null_stats[i] = autocorr_diff_stat(df, shifted)
    valid = np.isfinite(null_stats)
    p_value = (np.sum(np.abs(null_stats[valid]) >= abs(observed)) + 1) / (valid.sum() + 1)
    return {
        "observed": observed,
        "null_mean": float(np.nanmean(null_stats)),
        "null_std": float(np.nanstd(null_stats)),
        "p_value": float(p_value),
        "n_perm": n_perm,
        "n_obs": n,
    }


def analyze_lag(returns: pd.Series, gex: pd.Series, lag: int, n_perm: int) -> str:
    lines = [f"--- lag={lag} (regime built from GEX known {lag} day(s) before the decision day) ---"]

    regime_raw = classify_regime_sign(gex)
    regime = lag_for_trading(regime_raw, lag=lag)

    counts = regime.value_counts()
    lines.append(f"Regime base rates: {dict(counts)}  "
                 f"({counts.get('positive', 0) / counts.sum():.1%} positive)")

    runs = find_runs(regime)
    run_lengths = pd.Series([end - start + pd.Timedelta(days=0) for _, start, end in runs])
    # count trading days per run instead (timedelta isn't meaningful across weekends)
    run_day_counts = []
    for label, start, end in runs:
        run_day_counts.append((label, len(returns.loc[start:end])))
    rdc = pd.DataFrame(run_day_counts, columns=["label", "days"])
    lines.append(f"Regime persistence: {len(runs)} runs, mean run length "
                 f"{rdc['days'].mean():.1f} trading days "
                 f"(positive mean {rdc.loc[rdc.label=='positive','days'].mean():.1f}, "
                 f"negative mean {rdc.loc[rdc.label=='negative','days'].mean():.1f})")

    # --- Realized vol by regime ---
    abs_ret = returns.abs()
    aligned = pd.concat([regime.rename("label"), abs_ret.rename("abs_ret"), returns.rename("ret")], axis=1).dropna()

    pos_abs = aligned.loc[aligned.label == "positive", "abs_ret"]
    neg_abs = aligned.loc[aligned.label == "negative", "abs_ret"]
    pos_ret = aligned.loc[aligned.label == "positive", "ret"]
    neg_ret = aligned.loc[aligned.label == "negative", "ret"]

    lines.append("")
    lines.append("Realized vol by regime (next-day |log return|, annualized):")
    lines.append(f"  positive: mean|r|={pos_abs.mean()*100*np.sqrt(252):.2f}%  std(r)={pos_ret.std()*100*np.sqrt(252):.2f}%  n={len(pos_abs)}")
    lines.append(f"  negative: mean|r|={neg_abs.mean()*100*np.sqrt(252):.2f}%  std(r)={neg_ret.std()*100*np.sqrt(252):.2f}%  n={len(neg_abs)}")

    from scipy import stats as spstats
    welch = spstats.ttest_ind(pos_abs, neg_abs, equal_var=False)
    lines.append(f"  Welch t-test on |r|: t={welch.statistic:.3f} p={welch.pvalue:.4f}")

    perm = circular_shift_permutation_test(
        aligned["label"], aligned["abs_ret"], diff_mean_abs_ret, n_perm=n_perm
    )
    lines.append(f"  Circular-shift permutation test (preserves autocorrelation): "
                 f"diff(pos-neg)={perm['observed']:.6f}  null_mean={perm['null_mean']:.6f}  "
                 f"p={perm['p_value']:.4f}")

    perm_std = circular_shift_permutation_test(
        aligned["label"], aligned["ret"], diff_std_ret, n_perm=n_perm
    )
    lines.append(f"  Circular-shift permutation test on std(r): "
                 f"diff(pos-neg)={perm_std['observed']:.6f}  p={perm_std['p_value']:.4f}")

    # --- Mean reversion: lag-1 autocorrelation by regime ---
    r_lag = returns.shift(1)
    ac_df = pd.concat([regime.rename("label"), returns.rename("r"), r_lag.rename("r_lag")], axis=1).dropna()
    pos_ac = ac_df.loc[ac_df.label == "positive"]
    neg_ac = ac_df.loc[ac_df.label == "negative"]
    pos_corr = pos_ac["r"].corr(pos_ac["r_lag"])
    neg_corr = neg_ac["r"].corr(neg_ac["r_lag"])

    lines.append("")
    lines.append("Mean reversion: lag-1 autocorrelation of returns by regime")
    lines.append(f"  positive: corr(r_t, r_t-1) = {pos_corr:.4f}  (n={len(pos_ac)})")
    lines.append(f"  negative: corr(r_t, r_t-1) = {neg_corr:.4f}  (n={len(neg_ac)})")
    lines.append("  (hypothesis: positive should be more NEGATIVE (reversal), "
                 "negative should be more POSITIVE (trend))")

    ac_test = circular_shift_autocorr_test(ac_df, n_perm=n_perm)
    lines.append(f"  Circular-shift permutation test on autocorr diff (pos-neg): "
                 f"observed={ac_test['observed']:.4f}  null_mean={ac_test['null_mean']:.4f}  "
                 f"p={ac_test['p_value']:.4f}")

    # --- Variance ratio on contiguous regime runs ---
    lines.append("")
    lines.append("Variance ratio (VR<1 = mean-reverting, VR>1 = trending), on contiguous regime runs:")
    for q in (5, 10):
        vr = regime_variance_ratios(returns, regime, q=q, min_run=q * 3)
        lines.append(f"  VR({q}): positive={vr['positive']['vr_mean']:.3f} "
                     f"(n_runs={vr['positive']['n_runs']}, days={vr['positive']['total_days']})   "
                     f"negative={vr['negative']['vr_mean']:.3f} "
                     f"(n_runs={vr['negative']['n_runs']}, days={vr['negative']['total_days']})")

    return "\n".join(lines), aligned


def plot_vol_by_regime(aligned: pd.DataFrame, path):
    fig, axes = plt.subplots(1, 2, figsize=(9, 4.5))
    for ax, col, title in [
        (axes[0], "abs_ret", "mean |daily return| by regime"),
        (axes[1], "ret", "std(daily return) by regime"),
    ]:
        groups = ["positive", "negative"]
        if col == "abs_ret":
            means = [aligned.loc[aligned.label == g, col].mean() * 100 * np.sqrt(252) for g in groups]
            sems = [aligned.loc[aligned.label == g, col].sem() * 100 * np.sqrt(252) for g in groups]
        else:
            means = [aligned.loc[aligned.label == g, col].std() * 100 * np.sqrt(252) for g in groups]
            sems = [0, 0]  # std has no simple SEM here; omit error bars for this panel
        ax.bar(groups, means, yerr=sems, capsize=4, color=["#2a9d8f", "#e76f51"])
        ax.set_title(title)
        ax.set_ylabel("annualized %")
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def main():
    panel = pd.read_csv(config.PROCESSED_DIR / "panel.csv", index_col="date", parse_dates=["date"])
    sub = panel.loc[config.GEX_HISTORY_START:]
    returns = sub["spx_log_ret"].dropna()
    gex = sub["gex"].dropna()

    report_lines = [REALTIME_AVAILABILITY_NOTE]
    report_lines.append(f"Sample: {sub.index.min().date()} -> {sub.index.max().date()} (GEX-covered window)")
    report_lines.append("")

    n_perm = 5000
    text1, aligned1 = analyze_lag(returns, gex, lag=1, n_perm=n_perm)
    report_lines.append(text1)
    report_lines.append("")
    text2, _ = analyze_lag(returns, gex, lag=2, n_perm=n_perm)
    report_lines.append(text2)

    report = "\n".join(report_lines)
    print(report)

    out_path = config.RESULTS_DIR / "checkpoint3_regime_standalone.txt"
    out_path.write_text(report + "\n")
    print(f"\nWrote report to {out_path}")

    plot_vol_by_regime(aligned1, config.RESULTS_DIR / "regime_vol_comparison.png")
    print(f"Wrote plot to {config.RESULTS_DIR}/regime_vol_comparison.png")


if __name__ == "__main__":
    main()
