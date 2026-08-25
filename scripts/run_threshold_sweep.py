"""Re-derive the Final-1% crossing signal at multiple entry thresholds against
the same stratified market sample, and export a full trade-level CSV (with
liquidity depth caps, fees, category labels -- everything the Kelly backtest
needs) per threshold. The expensive part (per-token lifetime price history)
is fetched once and disk-cached; detect_crossing() is then re-run against
that cache for every threshold >= COARSE_APPROACH_THRESHOLD (0.97), so only
the first threshold in the list pays for live API calls in a fresh clone.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import polymarket_final_pct as pmf

RESULTS_DIR = Path(__file__).resolve().parents[1] / "results" / "polymarket_final_pct"


def build_trades_for_threshold(sample, threshold, fill_type="maker"):
    sig_cfg = pmf.SignalConfig(threshold=threshold, n_consecutive=3)
    cfg = pmf.BacktestConfig(signal=sig_cfg, position_notional=100.0,
                              gas=pmf.GasAssumptions(relayer_sponsored=True))
    crossings = pmf.find_all_crossings(sample, sig_cfg)
    fill = pmf.FillAssumptions(fill_type=fill_type)
    tdf = pmf.simulate_trades_for_fill(crossings, fill, cfg)
    return tdf


def main(sample_size, thresholds, out_suffix=""):
    t0 = time.time()
    print(f"Fetching Gamma census ...", flush=True)
    census = pmf.fetch_resolved_markets_census()
    print(f"  census size: {len(census):,}  ({time.time()-t0:.0f}s)", flush=True)

    sample = pmf.stratified_sample_markets(census, n_target=sample_size)
    sample = [m for m in sample if pmf._safe_json_list(m.get("clobTokenIds"))]
    print(f"  sample size: {len(sample):,}", flush=True)

    for thr in thresholds:
        t1 = time.time()
        print(f"\n=== threshold {thr} ===", flush=True)
        tdf = build_trades_for_threshold(sample, thr, "maker")
        n_flips = int((~tdf["won"]).sum()) if not tdf.empty else 0
        print(f"  {len(tdf)} trades, {n_flips} flips  ({time.time()-t1:.0f}s)", flush=True)
        out_path = RESULTS_DIR / f"trades_maker_thr{str(thr).replace('.', '')}{out_suffix}.csv"
        tdf.to_csv(out_path, index=False)
        print(f"  wrote {out_path}", flush=True)

    print(f"\nTotal time: {time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--sample-size", type=int, default=4000)
    p.add_argument("--thresholds", type=str, default="0.98,0.985,0.99,0.995,0.999")
    p.add_argument("--suffix", type=str, default="")
    args = p.parse_args()
    thresholds = [float(x) for x in args.thresholds.split(",")]
    main(args.sample_size, thresholds, args.suffix)
