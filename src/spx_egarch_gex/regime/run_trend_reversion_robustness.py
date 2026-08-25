"""Checkpoint 3 follow-up: does the trend/mean-reversion regime split show up
under other lenses, given that close-to-close lag-1 autocorrelation did NOT
confirm it (positive regime corr=-0.052, negative regime corr=-0.234 --
backwards from the "negative gamma = momentum" prediction, p=0.19)?

Three angles, all still walk-forward-safe (regime lagged 1 day):

1. Intraday vs overnight decomposition. Dealer gamma hedging happens DURING
   the cash session; overnight gaps reflect unrelated news/macro flow. If
   the close-to-close test is being contaminated by overnight reversals
   that have nothing to do with dealer flow, the effect might show up
   cleanly in open-to-close returns specifically, even if it's invisible
   in the close-to-close series.
2. Nonparametric sign-continuation rate at lag 1 (robust to the handful of
   extreme-return crisis days that can dominate a correlation coefficient
   in a 348-observation negative-gamma sample).
3. Weekly-horizon trend test: correlation between trailing 5-day return and
   forward 5-day return by regime, since gamma positioning is a slower-
   moving signal (mean run length is weeks) than single-day autocorrelation.

Run as: python -m spx_egarch_gex.regime.run_trend_reversion_robustness
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from spx_egarch_gex import config
from spx_egarch_gex.regime.classifier import classify_regime_sign, lag_for_trading
from spx_egarch_gex.regime.run_standalone_backtest import circular_shift_autocorr_test
from spx_egarch_gex.stats.inference import circular_shift_permutation_test


def load_ohlc_returns() -> pd.DataFrame:
    spx = pd.read_csv(config.RAW_DIR / "spx.csv", index_col="date", parse_dates=["date"])
    df = pd.DataFrame(index=spx.index)
    df["intraday_ret"] = np.log(spx["Close"] / spx["Open"])
    df["overnight_ret"] = np.log(spx["Open"] / spx["Close"].shift(1))
    df["close_to_close"] = np.log(spx["Close"] / spx["Close"].shift(1))
    # sanity check: intraday + overnight should equal close-to-close
    check = (df["intraday_ret"] + df["overnight_ret"] - df["close_to_close"]).abs()
    assert check.dropna().max() < 1e-8, f"decomposition mismatch: max diff {check.max()}"
    return df


def sign_continuation_stat(labels: pd.Series, agree: pd.Series) -> float:
    """agree[t] = 1 if sign(r_t) == sign(r_{t-1}) else 0. Stat = P(agree|positive) - P(agree|negative)."""
    pos = agree[labels == "positive"]
    neg = agree[labels == "negative"]
    if len(pos) < 30 or len(neg) < 30:
        return np.nan
    return float(pos.mean() - neg.mean())


def analyze_return_series(name: str, r: pd.Series, regime: pd.Series, n_perm: int) -> str:
    lines = [f"--- {name} ---"]

    r_lag = r.shift(1)
    df = pd.concat([regime.rename("label"), r.rename("r"), r_lag.rename("r_lag")], axis=1).dropna()
    pos = df.loc[df.label == "positive"]
    neg = df.loc[df.label == "negative"]

    pos_corr = pos["r"].corr(pos["r_lag"])
    neg_corr = neg["r"].corr(neg["r_lag"])
    lines.append(f"lag-1 autocorr: positive={pos_corr:.4f} (n={len(pos)})  negative={neg_corr:.4f} (n={len(neg)})")

    ac_test = circular_shift_autocorr_test(df, n_perm=n_perm)
    lines.append(f"  permutation test on (pos-neg) autocorr diff: observed={ac_test['observed']:.4f} "
                 f"null_mean={ac_test['null_mean']:.4f}  p={ac_test['p_value']:.4f}")

    agree = (np.sign(df["r"]) == np.sign(df["r_lag"])).astype(float)
    agree.name = "agree"
    pos_cont = agree[df.label == "positive"].mean()
    neg_cont = agree[df.label == "negative"].mean()
    lines.append(f"sign-continuation P(same sign as yesterday): positive={pos_cont:.3f}  negative={neg_cont:.3f}  "
                 "(0.5=random; >0.5=momentum; <0.5=reversal)")

    cont_test = circular_shift_permutation_test(df["label"], agree, sign_continuation_stat, n_perm=n_perm)
    lines.append(f"  permutation test on (pos-neg) continuation-rate diff: observed={cont_test['observed']:.4f} "
                 f"p={cont_test['p_value']:.4f}")

    lines.append(f"realized vol (annualized): positive={pos['r'].std()*100*np.sqrt(252):.2f}%  "
                 f"negative={neg['r'].std()*100*np.sqrt(252):.2f}%")

    return "\n".join(lines)


def weekly_trend_test(returns: pd.Series, regime: pd.Series, n_perm: int) -> str:
    lines = ["--- weekly-horizon trend test (trailing 5d return vs forward 5d return) ---"]
    trailing = returns.rolling(5).sum()  # trailing[t] = sum(returns[t-4..t])
    forward = returns.iloc[::-1].rolling(5).sum().iloc[::-1].shift(-1)  # forward[t] = sum(returns[t+1..t+5])

    df = pd.concat(
        [regime.rename("label"), trailing.rename("trailing"), forward.rename("forward")], axis=1
    ).dropna()
    pos = df.loc[df.label == "positive"]
    neg = df.loc[df.label == "negative"]
    pos_corr = pos["trailing"].corr(pos["forward"])
    neg_corr = neg["trailing"].corr(neg["forward"])
    lines.append(f"corr(trailing 5d, forward 5d): positive={pos_corr:.4f} (n={len(pos)})  "
                 f"negative={neg_corr:.4f} (n={len(neg)})")
    lines.append("(hypothesis: positive should be more NEGATIVE (reversal), negative should be more POSITIVE (trend))")

    # custom circular-shift test (same pattern as autocorr, but on trailing/forward pair)
    n = len(df)
    rng = np.random.default_rng(0)
    label_arr = df["label"].to_numpy()

    def corr_diff(lab):
        p = df.loc[lab == "positive"]
        ng = df.loc[lab == "negative"]
        if len(p) < 30 or len(ng) < 30:
            return np.nan
        return p["trailing"].corr(p["forward"]) - ng["trailing"].corr(ng["forward"])

    observed = corr_diff(df["label"])
    null_stats = np.empty(n_perm)
    for i in range(n_perm):
        shift = rng.integers(1, n)
        shifted = pd.Series(np.roll(label_arr, shift), index=df.index)
        null_stats[i] = corr_diff(shifted)
    valid = np.isfinite(null_stats)
    p_value = (np.sum(np.abs(null_stats[valid]) >= abs(observed)) + 1) / (valid.sum() + 1)
    lines.append(f"permutation test on (pos-neg) corr diff: observed={observed:.4f}  "
                 f"null_mean={np.nanmean(null_stats):.4f}  p={p_value:.4f}")
    return "\n".join(lines)


def main():
    panel = pd.read_csv(config.PROCESSED_DIR / "panel.csv", index_col="date", parse_dates=["date"])
    sub = panel.loc[config.GEX_HISTORY_START:]
    gex = sub["gex"].dropna()
    regime_raw = classify_regime_sign(gex)
    regime = lag_for_trading(regime_raw, lag=1)

    ohlc = load_ohlc_returns().loc[config.GEX_HISTORY_START:]

    n_perm = 5000
    report_lines = [f"Sample: {sub.index.min().date()} -> {sub.index.max().date()}, lag=1 regime\n"]

    report_lines.append(analyze_return_series("intraday (open-to-close)", ohlc["intraday_ret"], regime, n_perm))
    report_lines.append("")
    report_lines.append(analyze_return_series("overnight (prev close-to-open)", ohlc["overnight_ret"], regime, n_perm))
    report_lines.append("")
    report_lines.append(analyze_return_series("close-to-close (for reference, matches checkpoint3)",
                                               ohlc["close_to_close"], regime, n_perm))
    report_lines.append("")

    returns = sub["spx_log_ret"].dropna()
    report_lines.append(weekly_trend_test(returns, regime, n_perm))

    report = "\n".join(report_lines)
    print(report)

    out_path = config.RESULTS_DIR / "checkpoint3b_trend_reversion_robustness.txt"
    out_path.write_text(report + "\n")
    print(f"\nWrote report to {out_path}")


if __name__ == "__main__":
    main()
