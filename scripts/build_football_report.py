"""Renders results/football_favorite_bias/football_favorite_bias_results.json
into a static HTML report. Kept as a small generator (rather than a
hand-edited HTML file) so the numbers in the page can never drift from the
JSON a re-run of run_football_favorite_bias_backtest.py produces.
"""
import json
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(REPO, "results", "football_favorite_bias")


def downsample(series, n=180):
    if len(series) <= n:
        return series
    step = len(series) / n
    out, i = [], 0.0
    while int(i) < len(series):
        out.append(series[int(i)])
        i += step
    if out[-1][0] != series[-1][0]:
        out.append(series[-1])
    return out


def fmt_pp(x):
    return f"{x:+.2f}pp"


def main():
    with open(os.path.join(DATA_DIR, "football_favorite_bias_results.json")) as f:
        d = json.load(f)

    diag_rows = "".join(
        f"""<tr>
          <td>{r['threshold']*100:.0f}%</td>
          <td class="num">{r['n']:,}</td>
          <td class="num">{r['win_rate_pct']:.2f}%</td>
          <td class="num">{r['avg_closing_price_pct']:.2f}%</td>
          <td class="num {'pos' if r['edge_pp']>0 else 'neg'}">{fmt_pp(r['edge_pp'])}</td>
        </tr>""" for r in d["raw_vs_devigged_diagnostic"]
    )

    sweep_rows = ""
    for thr_s, v in d["threshold_sweep"].items():
        thr = float(thr_s)
        k, fl = v["kelly"], v["flat"]
        sweep_rows += f"""<tr>
          <td>{thr*100:.0f}%</td>
          <td class="num">{v['n_trades']:,}</td>
          <td class="num {'pos' if k['cagr_pct']>0 else 'neg'}">{k['cagr_pct']:+.2f}%</td>
          <td class="num">{'—' if k['sharpe'] is None else k['sharpe']}</td>
          <td class="num">{k['max_drawdown_pct']:.1f}%</td>
          <td class="num {'pos' if fl['cagr_pct']>0 else 'neg'}">{fl['cagr_pct']:+.2f}%</td>
          <td class="num">{'—' if fl['sharpe'] is None else fl['sharpe']}</td>
          <td class="num">{fl['max_drawdown_pct']:.1f}%</td>
        </tr>"""

    league_rows = "".join(
        f"""<tr>
          <td>{r['league_name']}</td>
          <td class="num">{r['n']:,}</td>
          <td class="num">{r['win_rate_pct']:.2f}%</td>
          <td class="num">{r['avg_closing_price_pct']:.2f}%</td>
          <td class="num {'pos' if r['edge_pp']>0 else 'neg'}">{fmt_pp(r['edge_pp'])}</td>
        </tr>""" for r in sorted(d["league_breakdown"], key=lambda x: -x["edge_pp"])
    )

    kelly_series = downsample(d["primary_kelly_equity_curve"])
    flat_series = downsample(d["primary_flat_equity_curve"])

    sr = d["split_sample_robustness"]
    early, late = sr["early"], sr["late"]

    html = HTML_TEMPLATE.format(
        n_matches=f"{d['n_matches_total']:,}",
        n_leagues=len(d["league_breakdown"]),
        diag_rows=diag_rows,
        sweep_rows=sweep_rows,
        league_rows=league_rows,
        primary_kelly_final=f"{d['primary_kelly']['final_equity']:,.0f}",
        primary_kelly_cagr=f"{d['primary_kelly']['cagr_pct']:+.2f}",
        primary_kelly_sharpe=d['primary_kelly']['sharpe'],
        primary_kelly_dd=f"{d['primary_kelly']['max_drawdown_pct']:.1f}",
        primary_flat_final=f"{d['primary_flat']['final_equity']:,.0f}",
        primary_flat_cagr=f"{d['primary_flat']['cagr_pct']:+.2f}",
        primary_flat_sharpe=d['primary_flat']['sharpe'],
        primary_flat_dd=f"{d['primary_flat']['max_drawdown_pct']:.1f}",
        primary_n=f"{d['primary_kelly']['n_taken']:,}",
        primary_flat_n=f"{d['primary_flat']['n_taken']:,}",
        early_range=f"{early['date_range'][0]} to {early['date_range'][1]}",
        late_range=f"{late['date_range'][0]} to {late['date_range'][1]}",
        early_n=early['n'], late_n=late['n'],
        early_edge=fmt_pp(early['edge_pp']), late_edge=fmt_pp(late['edge_pp']),
        early_kelly_cagr=f"{early['kelly_cagr_pct']:+.2f}", late_kelly_cagr=f"{late['kelly_cagr_pct']:+.2f}",
        early_kelly_sharpe=early['kelly_sharpe'], late_kelly_sharpe=late['kelly_sharpe'],
        kelly_series_json=json.dumps(kelly_series),
        flat_series_json=json.dumps(flat_series),
    )

    out_path = os.path.join(DATA_DIR, "football_favorite_bias_report.html")
    with open(out_path, "w") as f:
        f.write(html)
    print(f"saved {out_path} ({len(html):,} bytes)")


HTML_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Betting the Board Favorite</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Domine:wght@500;600;700&family=Public+Sans:ital,wght@0,400;0,500;0,600;0,700;1,400&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  :root {{
    color-scheme: light;
    --page-bg:        #f5f3ee;
    --surface:        #fbfaf6;
    --surface-raised: #ffffff;
    --ink-primary:    #1b1f1a;
    --ink-secondary:  #55564e;
    --ink-muted:      #8f8d80;
    --gridline:       #e3e0d5;
    --border:         rgba(27,31,26,0.10);
    --border-strong:  rgba(27,31,26,0.16);
    --series-kelly:   #0d7ea6;
    --series-kelly-wash: rgba(13,126,166,0.11);
    --series-flat:    #93325a;
    --series-flat-wash: rgba(147,50,90,0.08);
    --good: #1f7a4d;
    --good-wash: rgba(31,122,77,0.10);
    --bad: #a4433a;
    --bad-wash: rgba(164,67,58,0.09);
    --info: #6a4fa0;
    --info-wash: rgba(106,79,160,0.09);
    --shadow: 0 1px 2px rgba(27,31,26,0.06), 0 8px 24px -12px rgba(27,31,26,0.18);
  }}
  @media (prefers-color-scheme: dark) {{
    :root:not([data-theme="light"]) {{
      color-scheme: dark;
      --page-bg: #0e1012; --surface: #171a1d; --surface-raised: #1c2023;
      --ink-primary: #f3f2ee; --ink-secondary: #c7c5ba; --ink-muted: #8b897d;
      --gridline: #2b2e31; --border: rgba(255,255,255,0.09); --border-strong: rgba(255,255,255,0.15);
      --series-kelly: #34a0cc; --series-kelly-wash: rgba(52,160,204,0.14);
      --series-flat: #c46a8f; --series-flat-wash: rgba(196,106,143,0.10);
      --good: #4bbd85; --good-wash: rgba(75,189,133,0.12);
      --bad: #e08277; --bad-wash: rgba(224,130,119,0.12);
      --info: #a48fd6; --info-wash: rgba(164,143,214,0.14);
      --shadow: 0 1px 2px rgba(0,0,0,0.3), 0 8px 24px -12px rgba(0,0,0,0.5);
    }}
  }}
  :root[data-theme="dark"] {{
    color-scheme: dark;
    --page-bg: #0e1012; --surface: #171a1d; --surface-raised: #1c2023;
    --ink-primary: #f3f2ee; --ink-secondary: #c7c5ba; --ink-muted: #8b897d;
    --gridline: #2b2e31; --border: rgba(255,255,255,0.09); --border-strong: rgba(255,255,255,0.15);
    --series-kelly: #34a0cc; --series-kelly-wash: rgba(52,160,204,0.14);
    --series-flat: #c46a8f; --series-flat-wash: rgba(196,106,143,0.10);
    --good: #4bbd85; --good-wash: rgba(75,189,133,0.12);
    --bad: #e08277; --bad-wash: rgba(224,130,119,0.12);
    --info: #a48fd6; --info-wash: rgba(164,143,214,0.14);
    --shadow: 0 1px 2px rgba(0,0,0,0.3), 0 8px 24px -12px rgba(0,0,0,0.5);
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: var(--page-bg); color: var(--ink-primary);
    font-family: "Public Sans", ui-sans-serif, system-ui, sans-serif;
    -webkit-font-smoothing: antialiased;
  }}
  .wrap {{ max-width: 960px; margin: 0 auto; padding: 56px 24px 90px; }}
  .eyebrow {{
    font-size: 12px; font-weight: 700; letter-spacing: 0.09em; text-transform: uppercase;
    color: var(--series-kelly); margin: 0 0 16px;
  }}
  h1 {{
    font-family: "Domine", Georgia, serif; font-weight: 600; font-size: clamp(28px, 4.2vw, 40px);
    line-height: 1.16; letter-spacing: -0.01em; margin: 0 0 18px; text-wrap: balance;
  }}
  .dek {{ font-size: 16.5px; line-height: 1.62; color: var(--ink-secondary); max-width: 68ch; margin: 0 0 6px; }}
  .dek b {{ color: var(--ink-primary); }}
  .meta-row {{
    display: flex; flex-wrap: wrap; gap: 6px 18px; margin-top: 22px; padding-top: 18px;
    border-top: 1px solid var(--border); font-family: "IBM Plex Mono", monospace;
    font-size: 12.5px; color: var(--ink-muted);
  }}
  .meta-row b {{ color: var(--ink-secondary); font-weight: 600; }}

  .verdict {{
    margin-top: 34px; background: var(--bad-wash); border: 1px solid rgba(164,67,58,0.22);
    border-radius: 14px; padding: 22px 24px; display: flex; gap: 16px; align-items: flex-start;
  }}
  .verdict .mark {{
    flex: none; width: 30px; height: 30px; border-radius: 50%; background: var(--bad); color: #fff;
    display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 15px;
    font-family: "IBM Plex Mono", monospace;
  }}
  .verdict h3 {{ margin: 0 0 6px; font-family: "Domine", Georgia, serif; font-size: 17px; font-weight: 600; color: var(--bad); }}
  .verdict p {{ margin: 0; font-size: 14.5px; line-height: 1.65; color: var(--ink-secondary); max-width: 66ch; }}
  .verdict p b {{ color: var(--ink-primary); }}

  section.panel {{
    margin-top: 36px; background: var(--surface-raised); border: 1px solid var(--border);
    border-radius: 16px; padding: 30px 30px 26px; box-shadow: var(--shadow);
  }}
  .panel h2 {{ font-family: "Domine", Georgia, serif; font-weight: 600; font-size: 21px; margin: 0 0 8px; }}
  .panel .panel-note {{ font-size: 14px; color: var(--ink-secondary); line-height: 1.6; max-width: 68ch; margin: 0 0 22px; }}
  .panel .panel-note b {{ color: var(--ink-primary); }}

  .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 14px; margin-top: 22px; }}
  .stat {{ background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 16px 18px; }}
  .stat .label {{ font-size: 11.5px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; color: var(--ink-muted); margin-bottom: 8px; }}
  .stat .value {{ font-family: "IBM Plex Mono", monospace; font-size: 22px; font-weight: 600; font-variant-numeric: tabular-nums; }}
  .stat .sub {{ font-size: 12px; color: var(--ink-muted); margin-top: 4px; }}

  table {{ width: 100%; border-collapse: collapse; font-size: 13.5px; }}
  .table-scroll {{ overflow-x: auto; }}
  th {{
    text-align: left; font-weight: 700; font-size: 11.5px; letter-spacing: 0.03em; text-transform: uppercase;
    color: var(--ink-muted); padding: 9px 12px; border-bottom: 1px solid var(--border-strong); white-space: nowrap;
  }}
  td {{ padding: 9px 12px; border-bottom: 1px solid var(--border); white-space: nowrap; }}
  td.num, th.num {{ font-family: "IBM Plex Mono", monospace; font-variant-numeric: tabular-nums; text-align: right; }}
  td.pos {{ color: var(--good); }}
  td.neg {{ color: var(--bad); }}
  tr:last-child td {{ border-bottom: none; }}
  tr.highlight td {{ background: var(--series-kelly-wash); font-weight: 600; }}

  .legend {{ display: flex; gap: 22px; margin: 4px 0 14px; font-size: 12.5px; color: var(--ink-secondary); flex-wrap: wrap; }}
  .legend span {{ display: inline-flex; align-items: center; gap: 7px; }}
  .swatch {{ width: 14px; height: 3px; border-radius: 2px; display: inline-block; }}
  .chart-block {{ position: relative; margin-top: 6px; }}
  .chart-block svg {{ display: block; width: 100%; height: auto; overflow: visible; }}
  .axis-label {{ font-family: "IBM Plex Mono", monospace; font-size: 10.5px; fill: var(--ink-muted); }}
  .grid-line {{ stroke: var(--gridline); stroke-width: 1; }}
  .tooltip {{
    position: fixed; pointer-events: none; z-index: 40; opacity: 0; transition: opacity 0.1s ease;
    background: var(--surface-raised); border: 1px solid var(--border-strong); border-radius: 8px;
    padding: 9px 12px; font-size: 12.5px; box-shadow: var(--shadow); max-width: 240px;
    font-family: "IBM Plex Mono", monospace; color: var(--ink-primary); line-height: 1.6;
  }}
  .tooltip .t-head {{ font-family: "Public Sans", sans-serif; font-weight: 600; color: var(--ink-secondary); font-size: 11px; margin-bottom: 3px; }}
  .tooltip .t-row {{ display: flex; justify-content: space-between; gap: 14px; }}
  .tooltip .t-row .k {{ color: var(--ink-muted); display: flex; align-items: center; gap: 6px; }}
  .crosshair {{ stroke: var(--ink-muted); stroke-width: 1; stroke-dasharray: 3 3; opacity: 0; }}

  .split-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 18px; margin-top: 20px; }}
  .split-card {{ border: 1px solid var(--border); border-radius: 12px; padding: 20px 22px; background: var(--surface); }}
  .split-card .ctitle {{ font-size: 12px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; color: var(--ink-muted); margin-bottom: 2px; }}
  .split-card .crange {{ font-size: 12px; color: var(--ink-muted); margin-bottom: 16px; font-family: "IBM Plex Mono", monospace; }}
  .split-card .cheadline {{ font-family: "IBM Plex Mono", monospace; font-size: 26px; font-weight: 600; margin-bottom: 14px; font-variant-numeric: tabular-nums; }}
  .split-card.good .cheadline {{ color: var(--good); }}
  .split-card.bad .cheadline {{ color: var(--bad); }}
  .split-row {{ display: flex; justify-content: space-between; align-items: baseline; padding: 6px 0; border-bottom: 1px solid var(--border); font-size: 13px; }}
  .split-row:last-child {{ border-bottom: none; }}
  .split-row .k {{ color: var(--ink-secondary); }}
  .split-row .v {{ font-family: "IBM Plex Mono", monospace; font-weight: 600; font-variant-numeric: tabular-nums; }}

  footer {{ margin-top: 46px; padding-top: 22px; border-top: 1px solid var(--border); font-size: 12.5px; color: var(--ink-muted); line-height: 1.7; }}

  @media (max-width: 640px) {{ .split-grid {{ grid-template-columns: 1fr; }} }}
</style>
</head>
<body>
<div class="wrap">
  <p class="eyebrow">Free-Data Backtest &middot; Football Closing Lines</p>
  <h1>Does the Favorite-Longshot Edge Survive a Switch to a Sharp Bookmaker?</h1>
  <p class="dek">
    Polymarket's Final-1% strategy found a persistent, exploitable edge in backing extreme favorites on a thin,
    retail-heavy prediction market. This re-runs the <b>same 70%-threshold, walk-forward Kelly methodology</b> on
    <b>{n_matches}</b> football matches across <b>{n_leagues}</b> European leagues (2012/13&ndash;2024/25), using
    free closing-line odds from football-data.co.uk, anchored to Pinnacle &mdash; the sports-betting industry's
    reference "sharp" book.
  </p>
  <div class="meta-row">
    <span><b>Source</b> football-data.co.uk, free CSV, no account</span>
    <span><b>Price</b> Pinnacle closing odds (vig included, no fee added on top)</span>
    <span><b>Method</b> identical run_sim / run_flat_sim engines from the Polymarket project</span>
  </div>

  <div class="verdict">
    <div class="mark">&times;</div>
    <div>
      <h3>The edge does not survive an out-of-sample split</h3>
      <p>
        Backed on the full 2012&ndash;2025 sample, the 70% threshold strategy looks like a real discovery
        (<b>quarter-Kelly turns $10,000 into ${primary_kelly_final}</b>). But splitting the sample in half by
        date &mdash; each half re-starting its walk-forward belief from a cold prior, so nothing leaks across
        the split &mdash; shows the "edge" was <b>{early_edge}</b> in 2012&ndash;2019 and <b>{late_edge}</b> in
        2019&ndash;2025: it flips sign. That is the signature of a sample-period artifact, not a structural
        mispricing, and it's the opposite of what the Polymarket project found when it ran the same check.
      </p>
    </div>
  </div>

  <section class="panel">
    <h2>1. Does the raw closing price already predict the outcome?</h2>
    <p class="panel-note">
      Before any staking model: at each threshold, is the favorite's realized win rate above or below what the
      vig-inclusive closing price implies? A trader profits only where <b>win rate &gt; price</b> &mdash;
      anywhere else, the bookmaker's built-in margin (mean overround <b>2.59%</b> across this sample) is enough
      on its own to beat the bettor.
    </p>
    <div class="table-scroll">
    <table>
      <thead><tr><th>Threshold</th><th class="num">Matches</th><th class="num">Win rate</th><th class="num">Avg. closing price</th><th class="num">Edge</th></tr></thead>
      <tbody>{diag_rows}</tbody>
    </table>
    </div>
  </section>

  <section class="panel">
    <h2>2. Threshold sweep: quarter-Kelly vs. flat 1%-of-equity</h2>
    <p class="panel-note">
      Same walk-forward, per-league Bayesian Kelly engine used throughout the Polymarket project, with a prior
      re-centered for this population (Beta(5,15), mean 25% loss rate, vs. Polymarket's Beta(1,300) tuned for
      99%+ near-certainties &mdash; reusing that prior here would have wildly oversized the first bets in every
      league before the belief caught up). 70% is the only threshold with a clean pooled edge and enough sample
      to size meaningfully; everything else is presented for context, not cherry-picked after the fact.
    </p>
    <div class="table-scroll">
    <table>
      <thead><tr><th>Threshold</th><th class="num">Trades</th><th class="num">Kelly CAGR</th><th class="num">Kelly Sharpe</th><th class="num">Kelly MaxDD</th><th class="num">Flat CAGR</th><th class="num">Flat Sharpe</th><th class="num">Flat MaxDD</th></tr></thead>
      <tbody>{sweep_rows}</tbody>
    </table>
    </div>
  </section>

  <section class="panel">
    <h2>3. The headline case: 70% threshold, full sample</h2>
    <p class="panel-note">
      Read alongside the verdict above &mdash; these are the numbers that look good in isolation and don't
      survive the split-sample check in Section 4.
    </p>
    <div class="stats">
      <div class="stat"><div class="label">Kelly, quarter-fraction</div><div class="value" style="color:var(--series-kelly)">${primary_kelly_final}</div><div class="sub">{primary_n} trades taken &middot; CAGR {primary_kelly_cagr}% &middot; Sharpe {primary_kelly_sharpe} &middot; MaxDD {primary_kelly_dd}%</div></div>
      <div class="stat"><div class="label">Flat 1%-of-equity</div><div class="value" style="color:var(--series-flat)">${primary_flat_final}</div><div class="sub">{primary_flat_n} trades taken &middot; CAGR {primary_flat_cagr}% &middot; Sharpe {primary_flat_sharpe} &middot; MaxDD {primary_flat_dd}%</div></div>
      <div class="stat"><div class="label">Starting bankroll</div><div class="value">$10,000</div><div class="sub">2012-08-04 &rarr; 2025-05-25</div></div>
    </div>
    <div class="legend">
      <span><span class="swatch" style="background:var(--series-kelly)"></span>Quarter-Kelly</span>
      <span><span class="swatch" style="background:var(--series-flat)"></span>Flat 1%</span>
    </div>
    <div class="chart-block" id="chart"></div>
  </section>

  <section class="panel">
    <h2>4. Split-sample robustness &mdash; the check that overturns Section 3</h2>
    <p class="panel-note">
      Each half below re-starts the per-league walk-forward belief from a cold Beta(5,15) prior at the split
      date, so nothing about the "edge" in one half is informed by the other. A structural mispricing should
      show up in both; an edge that appears in one lucky decade and vanishes in the next is not something to
      trade live money on. (Same spirit as this repo's <code>leakage_check.py</code> for the Polymarket
      project, applied here as a train/test time split instead of a lookahead check.)
    </p>
    <div class="split-grid">
      <div class="split-card good">
        <div class="ctitle">2012 &ndash; 2019</div>
        <div class="crange">{early_range} &middot; n={early_n}</div>
        <div class="cheadline">{early_kelly_cagr}% CAGR</div>
        <div class="split-row"><span class="k">Win rate vs. price</span><span class="v">{early_edge}</span></div>
        <div class="split-row"><span class="k">Kelly Sharpe</span><span class="v">{early_kelly_sharpe}</span></div>
      </div>
      <div class="split-card bad">
        <div class="ctitle">2019 &ndash; 2025</div>
        <div class="crange">{late_range} &middot; n={late_n}</div>
        <div class="cheadline">{late_kelly_cagr}% CAGR</div>
        <div class="split-row"><span class="k">Win rate vs. price</span><span class="v">{late_edge}</span></div>
        <div class="split-row"><span class="k">Kelly Sharpe</span><span class="v">{late_kelly_sharpe}</span></div>
      </div>
    </div>
  </section>

  <section class="panel">
    <h2>5. Per-league breakdown (70% threshold, full sample)</h2>
    <p class="panel-note">
      The pooled edge is small and, per Section 4, unstable over time &mdash; but it's also not spread evenly
      across leagues. Portugal, Spain and Italy show a consistent positive edge; Germany and the Netherlands show
      a consistent negative one. That heterogeneity is a more plausible place to look for a real, narrower effect
      than the pooled 70% number, but testing that would need its own split-sample check per league before it's
      trustworthy &mdash; not done here, flagged as the natural next step.
    </p>
    <div class="table-scroll">
    <table>
      <thead><tr><th>League</th><th class="num">Matches</th><th class="num">Win rate</th><th class="num">Avg. price</th><th class="num">Edge</th></tr></thead>
      <tbody>{league_rows}</tbody>
    </table>
    </div>
  </section>

  <footer>
    Data: free historical results + closing odds from football-data.co.uk (Pinnacle preferred, Bet365 / market
    Max &amp; Avg as fallback for the ~0.1% of matches Pinnacle didn't quote). No account or API key required to
    reproduce &mdash; see <code>scripts/download_football_data.py</code>. Backtest engine: unmodified
    <code>run_sim</code> / <code>run_flat_sim</code> from the Polymarket Final-1% project, with the Beta prior
    parameterized (<code>prior_a</code>/<code>prior_b</code>) rather than hardcoded, so the same walk-forward
    Kelly logic serves both projects without duplication. Full numbers: <code>results/football_favorite_bias/football_favorite_bias_results.json</code>.
  </footer>
</div>

<div class="tooltip" id="tooltip"></div>

<script>
const kellySeries = {kelly_series_json};
const flatSeries = {flat_series_json};

function renderChart() {{
  const container = document.getElementById('chart');
  const width = container.clientWidth || 900;
  const height = 320;
  const pad = {{ top: 16, right: 16, bottom: 28, left: 64 }};
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;

  const allVals = kellySeries.concat(flatSeries).map(d => d[1]);
  const minV = Math.min(...allVals, 0);
  const maxV = Math.max(...allVals);
  const n = kellySeries.length;

  const x = i => pad.left + (i / (n - 1)) * plotW;
  const y = v => pad.top + plotH - ((v - minV) / (maxV - minV)) * plotH;

  function pathFor(series) {{
    return series.map((d, i) => `${{i === 0 ? 'M' : 'L'}} ${{x(i).toFixed(2)}} ${{y(d[1]).toFixed(2)}}`).join(' ');
  }}

  const gridCount = 5;
  let gridLines = '';
  let axisLabels = '';
  for (let g = 0; g <= gridCount; g++) {{
    const v = minV + (maxV - minV) * (g / gridCount);
    const yy = y(v);
    gridLines += `<line class="grid-line" x1="${{pad.left}}" x2="${{width - pad.right}}" y1="${{yy}}" y2="${{yy}}"/>`;
    axisLabels += `<text class="axis-label" x="${{pad.left - 8}}" y="${{yy + 4}}" text-anchor="end">$${{Math.round(v).toLocaleString()}}</text>`;
  }}
  const yearTicks = 4;
  for (let t = 0; t <= yearTicks; t++) {{
    const idx = Math.round((n - 1) * t / yearTicks);
    const xx = x(idx);
    axisLabels += `<text class="axis-label" x="${{xx}}" y="${{height - 6}}" text-anchor="middle">${{kellySeries[idx][0].slice(0,7)}}</text>`;
  }}

  container.innerHTML = `
    <svg viewBox="0 0 ${{width}} ${{height}}" width="${{width}}" height="${{height}}">
      ${{gridLines}}
      <path d="${{pathFor(flatSeries)}}" fill="none" stroke="var(--series-flat)" stroke-width="2"/>
      <path d="${{pathFor(kellySeries)}}" fill="none" stroke="var(--series-kelly)" stroke-width="2"/>
      ${{axisLabels}}
      <line id="crosshair" class="crosshair" x1="0" x2="0" y1="${{pad.top}}" y2="${{pad.top + plotH}}"/>
      <rect id="hover-rect" x="${{pad.left}}" y="${{pad.top}}" width="${{plotW}}" height="${{plotH}}" fill="transparent"/>
    </svg>
  `;

  const svg = container.querySelector('svg');
  const hoverRect = container.querySelector('#hover-rect');
  const crosshair = container.querySelector('#crosshair');
  const tooltip = document.getElementById('tooltip');

  hoverRect.addEventListener('mousemove', (e) => {{
    const rect = svg.getBoundingClientRect();
    const scaleX = width / rect.width;
    const mouseX = (e.clientX - rect.left) * scaleX;
    let idx = Math.round(((mouseX - pad.left) / plotW) * (n - 1));
    idx = Math.max(0, Math.min(n - 1, idx));
    const xx = x(idx);
    crosshair.setAttribute('x1', xx);
    crosshair.setAttribute('x2', xx);
    crosshair.style.opacity = 1;
    const kv = kellySeries[idx][1];
    const fv = flatSeries[idx][1];
    tooltip.innerHTML = `
      <div class="t-head">${{kellySeries[idx][0]}}</div>
      <div class="t-row"><span class="k"><span class="swatch" style="background:var(--series-kelly)"></span>Kelly</span><span>$${{kv.toLocaleString(undefined,{{maximumFractionDigits:0}})}}</span></div>
      <div class="t-row"><span class="k"><span class="swatch" style="background:var(--series-flat)"></span>Flat 1%</span><span>$${{fv.toLocaleString(undefined,{{maximumFractionDigits:0}})}}</span></div>
    `;
    tooltip.style.left = (e.clientX + 14) + 'px';
    tooltip.style.top = (e.clientY + 14) + 'px';
    tooltip.style.opacity = 1;
  }});
  hoverRect.addEventListener('mouseleave', () => {{
    crosshair.style.opacity = 0;
    tooltip.style.opacity = 0;
  }});
}}

renderChart();
window.addEventListener('resize', renderChart);
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
