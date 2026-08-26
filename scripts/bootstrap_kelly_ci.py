"""Block-bootstrap confidence intervals on the recommended Kelly, Capped
configuration's headline metrics (final equity, CAGR, max drawdown, Sharpe).

Every number reported so far is from ONE realized historical path -- one
specific sequence of which markets flipped and when. This resamples that
path at the level of calendar months (a moving block bootstrap): month-long
blocks of trades are drawn with replacement and stitched back-to-back into
a synthetic timeline of the same total length, preserving each block's
internal chronology (and therefore which positions were open at the same
time within a block) while varying which months appear, how often, and in
what order across resamples. The Kelly walk-forward sim is then re-run on
each synthetic timeline exactly as on the real one.
"""
import json
import os
import random
import sys
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_kelly_backtest import load, run_sim, DATA_DIR

N_BOOT = 1000
SEED = 42


def assign_blocks(trades):
    blocks = {}
    for r in trades:
        key = (r["entry_dt"].year, r["entry_dt"].month)
        blocks.setdefault(key, []).append(r)
    ordered_keys = sorted(blocks.keys())
    return blocks, ordered_keys


def build_synthetic_timeline(blocks, ordered_keys, rng):
    """Resample month-blocks with replacement, stitch back-to-back with a
    running time offset so blocks never overlap and none of run_sim's event-
    ordering / capital-commitment logic needs to change."""
    resampled_keys = [rng.choice(ordered_keys) for _ in range(len(ordered_keys))]
    synthetic = []
    cursor = None
    for key in resampled_keys:
        block_trades = blocks[key]
        block_start = min(r["entry_dt"] for r in block_trades)
        block_end = max(max(r["entry_dt"], r["resolve_dt"]) for r in block_trades)
        if cursor is None:
            offset = timedelta(0)
        else:
            offset = cursor - block_start
        for r in block_trades:
            r2 = dict(r)
            r2["entry_dt"] = r["entry_dt"] + offset
            r2["resolve_dt"] = r["resolve_dt"] + offset
            synthetic.append(r2)
        cursor = block_end + offset + timedelta(seconds=1)
    return synthetic


def main():
    maker_trades = load("trades_maker.csv")
    blocks, ordered_keys = assign_blocks(maker_trades)
    print(f"{len(maker_trades)} trades grouped into {len(ordered_keys)} monthly blocks "
          f"({ordered_keys[0]} -> {ordered_keys[-1]})")

    point = run_sim([dict(r) for r in maker_trades], fraction=0.25)
    print(f"\nPoint estimate (actual historical path): final=${point['final_equity']:,.0f}  "
          f"CAGR={point['cagr_pct']:.1f}%  MaxDD={point['max_drawdown_pct']:.1f}%  Sharpe={point['sharpe']}")

    rng = random.Random(SEED)
    boot_final, boot_cagr, boot_dd, boot_sharpe, boot_flips = [], [], [], [], []
    failures = 0
    for i in range(N_BOOT):
        synthetic = build_synthetic_timeline(blocks, ordered_keys, rng)
        res = run_sim(synthetic, fraction=0.25)
        if res is None:
            failures += 1
            continue
        boot_final.append(res["final_equity"])
        boot_cagr.append(res["cagr_pct"])
        boot_dd.append(res["max_drawdown_pct"])
        if res["sharpe"] is not None:
            boot_sharpe.append(res["sharpe"])
        boot_flips.append(res["n_flips_taken"])
        if (i + 1) % 200 == 0:
            print(f"  {i+1}/{N_BOOT} bootstrap iterations ...", flush=True)

    def pctiles(xs):
        xs = sorted(xs)
        n = len(xs)
        def p(q):
            idx = min(n - 1, max(0, int(round(q * (n - 1)))))
            return xs[idx]
        return {"p5": p(0.05), "p25": p(0.25), "median": p(0.50), "p75": p(0.75), "p95": p(0.95),
                "mean": sum(xs) / n, "n": n}

    results = {
        "point_estimate": point,
        "n_boot": N_BOOT, "n_blocks": len(ordered_keys), "failures": failures,
        "final_equity": pctiles(boot_final),
        "cagr_pct": pctiles(boot_cagr),
        "max_drawdown_pct": pctiles(boot_dd),
        "sharpe": pctiles(boot_sharpe),
        "n_flips_taken": pctiles(boot_flips),
        "pct_boot_runs_losing_money": sum(1 for x in boot_final if x < 10000) / len(boot_final) * 100,
    }

    print(f"\n=== Bootstrap distribution ({N_BOOT} resamples, {len(ordered_keys)}-month blocks) ===")
    for metric in ["final_equity", "cagr_pct", "max_drawdown_pct", "sharpe"]:
        p = results[metric]
        print(f"{metric:<18} p5={p['p5']:>10.2f}  p25={p['p25']:>10.2f}  median={p['median']:>10.2f}  "
              f"p75={p['p75']:>10.2f}  p95={p['p95']:>10.2f}   (point est. matches median direction: "
              f"{'yes' if abs(point[metric] - p['median']) < abs(p['p95']-p['p5']) else 'CHECK'})")
    print(f"\nFraction of bootstrap resamples that lost money: {results['pct_boot_runs_losing_money']:.1f}%")
    print(f"n_flips_taken distribution: {results['n_flips_taken']}")

    out_path = os.path.join(DATA_DIR, "kelly_bootstrap_ci.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nsaved {out_path}")


if __name__ == "__main__":
    main()
