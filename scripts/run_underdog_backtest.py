"""Tests the natural follow-up hypothesis from the favorite-side reports:
if the favorite is overpriced (win rate < price) in football and tennis,
shouldn't the OTHER side -- the longshot -- be underpriced, and therefore
profitable to back?

It isn't, and the reason is mechanical rather than a data quirk: the
"favorite overpriced" edge we measured (about +0.2pp in football's noisy
case, about +1 to +2pp in tennis) is smaller than the vig itself (the
bookmaker's margin, ~2.5-3% in both sports). Vig is a tax on the WHOLE
market, not something that lands entirely on one side -- so a favorite
mispricing smaller than the vig does not imply the other side clears its
own, separately vig-loaded break-even bar. This script's job is to actually
check that reasoning against real data rather than trust the algebra, using
the exact same matches, the same closing-line data, and the same Kelly/flat
engines as the favorite-side reports.

side="longshot": football bets the single least-likely of the two
non-favorite outcomes (the classic academic-literature "longshot"); tennis
bets the only other side (there being just two outcomes). Match selection
in both stays keyed to the FAVORITE crossing `threshold`, so this runs over
the identical trade population as the corresponding favorite-side report --
a clean same-games, opposite-side comparison.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
import football_favorite_bias as ffb
import tennis_favorite_bias as tfb
from run_kelly_backtest import run_sim, START_BANKROLL
from run_flat_stake_backtest import run_flat_sim

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(REPO, "results", "underdog_bias")

THRESHOLDS = [0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90]
PRIMARY_THRESHOLD = 0.70
PRIOR_A, PRIOR_B = 5, 15  # same weak Beta(5,15) prior as both favorite-side reports


def diagnostic(build_trades_fn, matches, label):
    print(f"=== {label}: longshot side, diagnostic vs. vig-inclusive price ===")
    rows = []
    for thr in THRESHOLDS:
        trades = build_trades_fn(matches, thr, side="longshot")
        if not trades:
            continue
        n = len(trades)
        wins = sum(1 for t in trades if t["won"])
        win_rate = wins / n
        avg_price = sum(t["entry_price"] for t in trades) / n
        edge_pp = (win_rate - avg_price) * 100
        rows.append({"threshold": thr, "n": n, "win_rate_pct": round(win_rate * 100, 2),
                      "avg_price_pct": round(avg_price * 100, 2), "edge_pp": round(edge_pp, 3)})
        print(f"  thr={thr:.2f}  n={n:6d}  win_rate={win_rate*100:6.2f}%  avg_price={avg_price*100:6.2f}%  edge={edge_pp:+.3f}pp")
    return rows


def sweep(build_trades_fn, matches, label):
    print(f"\n=== {label}: longshot side, Kelly (frac=0.25) vs flat 1%-of-equity ===")
    out = {}
    for thr in THRESHOLDS:
        trades = build_trades_fn(matches, thr, side="longshot")
        if len(trades) < 20:
            continue
        kelly = run_sim([dict(t) for t in trades], fraction=0.25, prior_a=PRIOR_A, prior_b=PRIOR_B)
        flat = run_flat_sim([dict(t) for t in trades], flat_frac=0.01)
        out[str(thr)] = {"n_trades": len(trades), "kelly": kelly, "flat": flat}
        print(f"  thr={thr:.2f}  n={len(trades):6d}  "
              f"Kelly: final=${kelly['final_equity']:>12,.2f} CAGR={kelly['cagr_pct']:>7.2f}% n_taken={kelly['n_taken']}  |  "
              f"Flat 1%: final=${flat['final_equity']:>12,.2f} CAGR={flat['cagr_pct']:>7.2f}%")
    return out


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    fm = ffb.load_matches()
    tm = tfb.load_matches()
    print(f"loaded {len(fm)} football matches, {len(tm)} tennis matches\n")

    football_diag = diagnostic(ffb.build_trades, fm, "FOOTBALL")
    print()
    tennis_diag = diagnostic(tfb.build_trades, tm, "TENNIS")

    football_sweep = sweep(ffb.build_trades, fm, "FOOTBALL")
    tennis_sweep = sweep(tfb.build_trades, tm, "TENNIS")

    print(f"\n=== Primary case ({PRIMARY_THRESHOLD:.0%}): favorite vs. longshot, same games, both sports ===")
    results = {"football": {}, "tennis": {}}
    for label, build_fn, matches in (("football", ffb.build_trades, fm), ("tennis", tfb.build_trades, tm)):
        fav_trades = build_fn(matches, PRIMARY_THRESHOLD, side="favorite")
        dog_trades = build_fn(matches, PRIMARY_THRESHOLD, side="longshot")
        fav_kelly = run_sim([dict(t) for t in fav_trades], fraction=0.25, prior_a=PRIOR_A, prior_b=PRIOR_B)
        fav_flat = run_flat_sim([dict(t) for t in fav_trades], flat_frac=0.01)
        dog_kelly = run_sim([dict(t) for t in dog_trades], fraction=0.25, prior_a=PRIOR_A, prior_b=PRIOR_B)
        dog_flat = run_flat_sim([dict(t) for t in dog_trades], flat_frac=0.01)
        print(f"  {label:<8} favorite: Kelly final=${fav_kelly['final_equity']:>12,.2f}  Flat final=${fav_flat['final_equity']:>12,.2f}   "
              f"({len(fav_trades)} matches)")
        print(f"  {label:<8} longshot: Kelly final=${dog_kelly['final_equity']:>12,.2f}  Flat final=${dog_flat['final_equity']:>12,.2f}   "
              f"({len(dog_trades)} matches)")
        results[label] = {
            "n_matches": len(fav_trades),
            "favorite_kelly": {k: fav_kelly[k] for k in ["final_equity", "total_return_pct", "cagr_pct", "sharpe", "n_taken"]},
            "favorite_flat": {k: fav_flat[k] for k in ["final_equity", "total_return_pct", "cagr_pct", "sharpe", "n_taken"]},
            "longshot_kelly": {k: dog_kelly[k] for k in ["final_equity", "total_return_pct", "cagr_pct", "sharpe", "n_taken"]},
            "longshot_flat": {k: dog_flat[k] for k in ["final_equity", "total_return_pct", "cagr_pct", "sharpe", "n_taken"]},
            "favorite_kelly_curve": fav_kelly["daily_series"],
            "longshot_kelly_curve": dog_kelly["daily_series"],
            "favorite_flat_curve": fav_flat["daily_series"],
            "longshot_flat_curve": dog_flat["daily_series"],
        }

    summary = {
        "primary_threshold": PRIMARY_THRESHOLD,
        "football_diagnostic": football_diag,
        "tennis_diagnostic": tennis_diag,
        "football_sweep": {
            k: {"n_trades": v["n_trades"],
                "kelly": {kk: v["kelly"][kk] for kk in ["final_equity", "total_return_pct", "cagr_pct", "sharpe", "n_taken"]},
                "flat": {kk: v["flat"][kk] for kk in ["final_equity", "total_return_pct", "cagr_pct", "sharpe", "n_taken"]}}
            for k, v in football_sweep.items()
        },
        "tennis_sweep": {
            k: {"n_trades": v["n_trades"],
                "kelly": {kk: v["kelly"][kk] for kk in ["final_equity", "total_return_pct", "cagr_pct", "sharpe", "n_taken"]},
                "flat": {kk: v["flat"][kk] for kk in ["final_equity", "total_return_pct", "cagr_pct", "sharpe", "n_taken"]}}
            for k, v in tennis_sweep.items()
        },
        "primary_comparison": results,
    }
    out_path = os.path.join(OUT_DIR, "underdog_bias_results.json")
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\nsaved {out_path}")


if __name__ == "__main__":
    main()
