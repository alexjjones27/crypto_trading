"""Out-of-sample / split-half check on the exact-score + narrow-weather-range
exclusion rule used throughout Kelly, Capped.

The rule was originally derived by manually reading all 7 flips in the full
sample -- which means "4 of 7 flips were exact-score/weather" is an
in-sample statistic about the very data it's applied to. This script checks
whether the rule is doing real, distributed work or whether it's mostly
validated by one lucky/unlucky cluster of trades, by splitting the sample
at its time median and re-measuring the rule's effect in each half
independently.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_kelly_backtest import load, DATA_DIR

EXACT_SCORE_RE = re.compile(r"^Exact Score:", re.I)
WEATHER_RE = re.compile(r"highest temperature.*(be between|be \d)", re.I)


def main():
    trades = load("trades_maker.csv")
    trades.sort(key=lambda r: r["entry_dt"])
    n = len(trades)
    split_idx = n // 2
    split_date = trades[split_idx]["entry_dt"]
    early, late = trades[:split_idx], trades[split_idx:]

    print(f"Total trades: {n}, split at {split_date.date()} (median entry date)")
    print(f"Early half: {len(early)} trades, {early[0]['entry_dt'].date()} -> {early[-1]['entry_dt'].date()}")
    print(f"Late half:  {len(late)} trades, {late[0]['entry_dt'].date()} -> {late[-1]['entry_dt'].date()}\n")

    def analyze(label, subset):
        flips = [r for r in subset if not r["won"]]
        excl_flips = [r for r in flips if r["excluded"]]
        excl_trades = [r for r in subset if r["excluded"]]
        non_excl = [r for r in subset if not r["excluded"]]
        non_excl_flips = [r for r in non_excl if not r["won"]]

        print(f"=== {label} ({len(subset)} trades) ===")
        print(f"  Flips: {len(flips)} total")
        for f in flips:
            tag = "EXCLUDED" if f["excluded"] else "tradeable"
            print(f"    [{tag}] {f['entry_dt'].date()}  {f['question'][:70]}")
        flip_rate_before = len(flips) / len(subset) if subset else float("nan")
        flip_rate_after = len(non_excl_flips) / len(non_excl) if non_excl else float("nan")
        print(f"  Exact-score/weather trades in this half: {len(excl_trades)} "
              f"({len(excl_flips)} of them flipped)")
        print(f"  Flip rate, unfiltered:  {flip_rate_before*100:.3f}%  ({len(flips)}/{len(subset)})")
        print(f"  Flip rate, after exclusion: {flip_rate_after*100:.3f}%  ({len(non_excl_flips)}/{len(non_excl)})")
        reduction = (flip_rate_before - flip_rate_after) / flip_rate_before * 100 if flip_rate_before > 0 else float("nan")
        print(f"  Relative flip-rate reduction from exclusion: {reduction:.1f}%\n")
        return {
            "label": label, "n_trades": len(subset), "n_flips": len(flips),
            "n_excluded_trades": len(excl_trades), "n_excluded_flips": len(excl_flips),
            "flip_rate_before": flip_rate_before, "flip_rate_after": flip_rate_after,
            "relative_reduction_pct": reduction,
        }

    results = {
        "split_date": split_date.isoformat(),
        "full_sample": analyze("Full sample", trades),
        "early_half": analyze("Early half (train period)", early),
        "late_half": analyze("Late half (test period)", late),
    }

    print("=== Verdict ===")
    early_r, late_r = results["early_half"], results["late_half"]
    if early_r["n_excluded_flips"] == 0:
        print("Early half: exclusion caught ZERO of its flips -- the rule provides no")
        print("measurable benefit in the first half of the sample on its own.")
    if late_r["relative_reduction_pct"] > early_r["relative_reduction_pct"] * 2:
        print("The rule's benefit is heavily concentrated in the LATE half of the sample.")
        print("That is consistent with either a genuinely emerging risk pattern (live/exact-")
        print("value markets becoming more common and riskier over time) or still just being")
        print("noise from a small flip count split into even smaller halves. n is too small")
        print("in either half to distinguish those two stories with confidence.")

    out_path = os.path.join(DATA_DIR, "exclusion_rule_validation.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nsaved {out_path}")


if __name__ == "__main__":
    main()
