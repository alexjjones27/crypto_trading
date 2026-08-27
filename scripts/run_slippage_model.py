"""Applies the real, data-grounded taker-slippage model (estimate_vwap_fill)
to the existing Final-1% trade population, and re-runs the backtest under
combined taker fee + real slippage vs. the maker-fill baseline (0 fee, 0
slippage assumed).

Framing matters here: "slippage" in the price-impact sense only applies to
a TAKER order (crossing the spread, consuming the book). This project's
headline numbers use MAKER fills throughout -- a resting limit order that
earns $0 fee (+ a rebate) precisely because it provides liquidity rather
than consuming it, so it doesn't "walk the tape" the way a market order
does. For maker fills the real unmodeled risk is fill uncertainty / adverse
selection (will a resting order at that price get filled by real flow at
all, and does the flow that fills it disproportionately happen right before
the market moves against it?), which is a different problem this script
does not attempt to model. What follows bounds the TAKER side of the
range: fee + real slippage, computed from realized trade prints rather than
assumed, using the SAME cached trade-tape data already on disk (zero new
network calls).
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import polymarket_final_pct as pmf
from run_kelly_backtest import load, run_sim, DATA_DIR, START_BANKROLL
from run_flat_stake_backtest import run_flat_sim

WINDOW_S = pmf.VWAP_WINDOW_S  # short window: price-impact measurement, not the depth-cap's 300s


def liquidity_tier(shares_per_min: float) -> str:
    if shares_per_min >= 20:
        return "high"
    if shares_per_min >= 2:
        return "medium"
    return "low"


def main(input_file="trades_maker.csv", out_suffix=""):
    maker_trades = load(input_file)
    tradeable = [r for r in maker_trades if not r["excluded"]]
    print(f"{len(tradeable)} tradeable trades from {input_file}; "
          f"estimating real taker slippage from cached trade tapes ...")

    rows = []
    n_no_data = 0
    for i, r in enumerate(tradeable):
        entry_price = r["entry_price"]
        shares = float(r["shares"]) if r["shares"] not in ("", None) else 100.0 / entry_price
        fit = pmf.estimate_vwap_fill(
            r["condition_id"], r["token_id"] if "token_id" in r else None,
            int(r["entry_dt"].timestamp()), entry_price, shares,
        ) if "token_id" in r else None
        if fit is None:
            n_no_data += 1
            rows.append({**r, "vwap": None, "slippage_frac": None, "fill_ratio": None})
            continue
        slippage_frac = fit["vwap"] / entry_price - 1.0
        rows.append({**r, "vwap": fit["vwap"], "slippage_frac": slippage_frac, "fill_ratio": fit["fill_ratio"],
                     "shares_per_min": fit["filled_shares"] / (WINDOW_S / 60.0)})
        if (i + 1) % 500 == 0:
            print(f"  {i+1}/{len(tradeable)} ...", flush=True)

    with_data = [r for r in rows if r["slippage_frac"] is not None]
    print(f"\n{len(with_data)}/{len(tradeable)} trades had BUY-side trade prints to estimate slippage from "
          f"({n_no_data} had none -- unknown, not assumed zero)")

    slips = sorted(r["slippage_frac"] for r in with_data)
    n = len(slips)
    def pctile(q):
        idx = min(n - 1, max(0, int(round(q * (n - 1)))))
        return slips[idx]
    print(f"\nSlippage distribution (fraction of entry price, buyer-adverse = positive):")
    print(f"  p5={pctile(0.05)*100:.3f}%  p25={pctile(0.25)*100:.3f}%  median={pctile(0.50)*100:.3f}%  "
          f"p75={pctile(0.75)*100:.3f}%  p95={pctile(0.95)*100:.3f}%  mean={sum(slips)/n*100:.3f}%")

    # slippage by liquidity tier
    tiers = {"high": [], "medium": [], "low": []}
    for r in with_data:
        tiers[liquidity_tier(r["shares_per_min"])].append(r["slippage_frac"])
    print(f"\nSlippage by realized liquidity near the crossing (shares/min in the {WINDOW_S}s window):")
    tier_summary = {}
    for tier in ("high", "medium", "low"):
        vals = tiers[tier]
        if not vals:
            continue
        vals_sorted = sorted(vals)
        med = vals_sorted[len(vals_sorted)//2]
        tier_summary[tier] = {"n": len(vals), "mean_pct": sum(vals)/len(vals)*100, "median_pct": med*100}
        print(f"  {tier:<7} n={len(vals):<5} mean={sum(vals)/len(vals)*100:>6.3f}%  median={med*100:>6.3f}%")

    fully_filled = sum(1 for r in with_data if r["fill_ratio"] is not None and r["fill_ratio"] >= 0.999)
    print(f"\n{fully_filled}/{len(with_data)} trades' desired size was fully fillable within the window "
          f"({WINDOW_S}s) from realized flow alone")

    # --- re-run the backtest with taker fee + real slippage applied ---
    slippage_by_key = {(x["market_id"], x["entry_time"]): x["slippage_frac"] for x in with_data}
    mean_slip = sum(slips) / n
    adjusted = []
    for r in tradeable:
        r2 = dict(r)
        slip = slippage_by_key.get((r["market_id"], r["entry_time"]), mean_slip)  # fall back to population mean if no data
        adj_price = min(0.999, r["entry_price"] * (1 + max(0.0, slip)))  # slippage only ever adverse for a buyer
        r2["entry_price"] = adj_price
        adjusted.append(r2)

    for r2 in adjusted:
        r2["fee_frac"] = pmf.taker_fee_frac_of_notional(r2["entry_price"], r2["category"])

    baseline_kelly = run_sim([dict(r) for r in maker_trades], fraction=0.25)
    slippage_kelly = run_sim([dict(r) for r in adjusted], fraction=0.25)
    baseline_flat = run_flat_sim([dict(r) for r in maker_trades], flat_frac=0.01)
    slippage_flat = run_flat_sim([dict(r) for r in adjusted], flat_frac=0.01)

    print(f"\n=== Kelly (fraction=0.25): maker baseline vs taker-fee + real-slippage ===")
    print(f"  baseline (maker, no slippage): final=${baseline_kelly['final_equity']:,.2f}  "
          f"CAGR={baseline_kelly['cagr_pct']:.2f}%  Sharpe={baseline_kelly['sharpe']}")
    print(f"  taker fee + real slippage:     final=${slippage_kelly['final_equity']:,.2f}  "
          f"CAGR={slippage_kelly['cagr_pct']:.2f}%  Sharpe={slippage_kelly['sharpe']}")
    print(f"\n=== Flat 1%: maker baseline vs taker-fee + real-slippage ===")
    print(f"  baseline (maker, no slippage): final=${baseline_flat['final_equity']:,.2f}  "
          f"CAGR={baseline_flat['cagr_pct']:.2f}%  Sharpe={baseline_flat['sharpe']}")
    print(f"  taker fee + real slippage:     final=${slippage_flat['final_equity']:,.2f}  "
          f"CAGR={slippage_flat['cagr_pct']:.2f}%  Sharpe={slippage_flat['sharpe']}")

    summary = {
        "n_tradeable": len(tradeable),
        "n_with_slippage_data": len(with_data),
        "n_no_data": n_no_data,
        "slippage_pctiles_pct": {"p5": pctile(0.05)*100, "p25": pctile(0.25)*100, "median": pctile(0.50)*100,
                                  "p75": pctile(0.75)*100, "p95": pctile(0.95)*100, "mean": sum(slips)/n*100},
        "slippage_by_liquidity_tier": tier_summary,
        "n_fully_fillable_in_window": fully_filled,
        "baseline_maker_kelly": {k: baseline_kelly[k] for k in ["final_equity", "total_return_pct", "cagr_pct", "max_drawdown_pct", "sharpe"]},
        "taker_plus_slippage_kelly": {k: slippage_kelly[k] for k in ["final_equity", "total_return_pct", "cagr_pct", "max_drawdown_pct", "sharpe"]},
        "baseline_maker_flat": {k: baseline_flat[k] for k in ["final_equity", "total_return_pct", "cagr_pct", "max_drawdown_pct", "sharpe"]},
        "taker_plus_slippage_flat": {k: slippage_flat[k] for k in ["final_equity", "total_return_pct", "cagr_pct", "max_drawdown_pct", "sharpe"]},
        "kelly_equity_curve_baseline": baseline_kelly["daily_series"],
        "kelly_equity_curve_slippage": slippage_kelly["daily_series"],
    }
    out_path = os.path.join(DATA_DIR, f"slippage_model_results{out_suffix}.json")
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\nsaved {out_path}")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--file", type=str, default="trades_maker.csv")
    p.add_argument("--suffix", type=str, default="")
    args = p.parse_args()
    main(args.file, args.suffix)
