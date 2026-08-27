"""Renders results/underdog_bias/underdog_bias_results.json into a static
HTML report. Same generator-not-hand-edited approach and visual tokens as
build_football_report.py / build_tennis_report.py.
"""
import json
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(REPO, "results", "underdog_bias")


def downsample(series, n=150):
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


def diag_rows_html(rows):
    return "".join(
        f"""<tr>
          <td>{r['threshold']*100:.0f}%</td>
          <td class="num">{r['n']:,}</td>
          <td class="num">{r['win_rate_pct']:.2f}%</td>
          <td class="num">{r['avg_price_pct']:.2f}%</td>
          <td class="num neg">{fmt_pp(r['edge_pp'])}</td>
        </tr>""" for r in rows
    )


def sweep_rows_html(sweep):
    out = ""
    for thr_s, v in sweep.items():
        thr = float(thr_s)
        k, fl = v["kelly"], v["flat"]
        out += f"""<tr>
          <td>{thr*100:.0f}%</td>
          <td class="num">{v['n_trades']:,}</td>
          <td class="num neg">{k['cagr_pct']:+.2f}%</td>
          <td class="num">${k['final_equity']:,.2f}</td>
          <td class="num neg">{fl['cagr_pct']:+.2f}%</td>
          <td class="num">${fl['final_equity']:,.2f}</td>
        </tr>"""
    return out


def main():
    with open(os.path.join(DATA_DIR, "underdog_bias_results.json")) as f:
        d = json.load(f)

    football_diag_rows = diag_rows_html(d["football_diagnostic"])
    tennis_diag_rows = diag_rows_html(d["tennis_diagnostic"])
    football_sweep_rows = sweep_rows_html(d["football_sweep"])
    tennis_sweep_rows = sweep_rows_html(d["tennis_sweep"])

    fc = d["primary_comparison"]["football"]
    tc = d["primary_comparison"]["tennis"]

    football_fav_series = downsample(fc["favorite_kelly_curve"])
    football_dog_series = downsample(fc["longshot_kelly_curve"])
    tennis_fav_series = downsample(tc["favorite_kelly_curve"])
    tennis_dog_series = downsample(tc["longshot_kelly_curve"])

    html = HTML_TEMPLATE.format(
        primary_threshold=f"{d['primary_threshold']*100:.0f}",
        football_diag_rows=football_diag_rows,
        tennis_diag_rows=tennis_diag_rows,
        football_sweep_rows=football_sweep_rows,
        tennis_sweep_rows=tennis_sweep_rows,
        football_n=f"{fc['n_matches']:,}",
        tennis_n=f"{tc['n_matches']:,}",
        football_fav_final=f"{fc['favorite_kelly']['final_equity']:,.2f}",
        football_fav_cagr=f"{fc['favorite_kelly']['cagr_pct']:+.2f}",
        football_dog_final=f"{fc['longshot_kelly']['final_equity']:,.2f}",
        football_dog_cagr=f"{fc['longshot_kelly']['cagr_pct']:+.2f}",
        tennis_fav_final=f"{tc['favorite_kelly']['final_equity']:,.2f}",
        tennis_fav_cagr=f"{tc['favorite_kelly']['cagr_pct']:+.2f}",
        tennis_dog_final=f"{tc['longshot_kelly']['final_equity']:,.2f}",
        tennis_dog_cagr=f"{tc['longshot_kelly']['cagr_pct']:+.2f}",
        football_fav_series_json=json.dumps(football_fav_series),
        football_dog_series_json=json.dumps(football_dog_series),
        tennis_fav_series_json=json.dumps(tennis_fav_series),
        tennis_dog_series_json=json.dumps(tennis_dog_series),
    )

    out_path = os.path.join(DATA_DIR, "underdog_bias_report.html")
    with open(out_path, "w") as f:
        f.write(html)
    print(f"saved {out_path} ({len(html):,} bytes)")


HTML_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Both Sides of the Vig</title>
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
    --series-fav:     #0d7ea6;
    --series-dog:     #93325a;
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
      --series-fav: #34a0cc; --series-dog: #c46a8f;
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
    --series-fav: #34a0cc; --series-dog: #c46a8f;
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
    color: var(--series-fav); margin: 0 0 16px;
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
  .sub-h {{
    font-family: "Public Sans", sans-serif; font-weight: 700; font-size: 13px; letter-spacing: 0.03em;
    text-transform: uppercase; color: var(--ink-secondary); margin: 26px 0 12px;
  }}
  .sub-h:first-of-type {{ margin-top: 0; }}

  .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 14px; margin: 22px 0; }}
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
  td.neg {{ color: var(--bad); }}
  tr:last-child td {{ border-bottom: none; }}

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

  footer {{ margin-top: 46px; padding-top: 22px; border-top: 1px solid var(--border); font-size: 12.5px; color: var(--ink-muted); line-height: 1.7; }}

  .two-col {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
  @media (max-width: 700px) {{ .two-col {{ grid-template-columns: 1fr; }} }}
</style>
</head>
<body>
<div class="wrap">
  <p class="eyebrow">Free-Data Backtest &middot; A Hypothesis Tested And Rejected</p>
  <h1>Both Sides of the Vig</h1>
  <p class="dek">
    The football and tennis reports both found the favorite slightly overpriced (win rate a touch below the
    quoted price). The obvious next question: if the favorite is overpriced, isn't the <b>other</b> side
    &mdash; the longshot &mdash; underpriced, and therefore worth backing? Same closing-line data, same games,
    same Kelly/flat engines, opposite side of the bet.
  </p>
  <div class="meta-row">
    <span><b>Football</b> longshot = least-likely of the two non-favorite outcomes</span>
    <span><b>Tennis</b> longshot = the only other side (two-outcome market)</span>
    <span><b>Selection</b> unchanged: still keyed to the favorite crossing the threshold</span>
  </div>

  <div class="verdict">
    <div class="mark">&times;</div>
    <div>
      <h3>No. The longshot side is worse, not better.</h3>
      <p>
        The reasoning that motivated this test was wrong, and it's worth saying why rather than just showing
        the number: the favorite's mispricing (win rate vs. price) was smaller than the bookmaker's own vig in
        both sports. Vig is a tax on the <b>whole market</b>, not something that lands only on the favorite's
        side &mdash; so a favorite edge smaller than the vig doesn't imply the other side clears its own,
        separately vig-loaded break-even bar. In practice, the longshot side carries even more of that margin
        than the favorite does (the textbook mechanism behind the favorite-longshot bias itself: bookmakers
        price the emotionally-appealing long-odds side with extra margin, knowing public money floods there
        regardless). At the {primary_threshold}% threshold, Kelly sizing against the longshot side wipes the
        bankroll to <b>$0</b> in both football and tennis.
      </p>
    </div>
  </div>

  <section class="panel">
    <h2>1. Longshot win rate vs. quoted price</h2>
    <p class="panel-note">
      Same diagnostic as both favorite-side reports, run on the other side of the same matches. Negative at
      every threshold, both sports &mdash; and in tennis, the negative edge actually <b>grows</b> as the
      threshold rises (the longer the odds, the worse the value), which is the textbook favorite-longshot-bias
      shape.
    </p>
    <div class="sub-h">Football</div>
    <div class="table-scroll">
    <table>
      <thead><tr><th>Threshold</th><th class="num">Matches</th><th class="num">Win rate</th><th class="num">Avg. price</th><th class="num">Edge</th></tr></thead>
      <tbody>{football_diag_rows}</tbody>
    </table>
    </div>
    <div class="sub-h">Tennis</div>
    <div class="table-scroll">
    <table>
      <thead><tr><th>Threshold</th><th class="num">Matches</th><th class="num">Win rate</th><th class="num">Avg. price</th><th class="num">Edge</th></tr></thead>
      <tbody>{tennis_diag_rows}</tbody>
    </table>
    </div>
  </section>

  <section class="panel">
    <h2>2. Threshold sweep: Kelly and flat sizing against the longshot edge</h2>
    <p class="panel-note">
      Both engines correctly punish the negative edge. Kelly reaches $0.00 fastest since it sizes up on any
      transient noisy-positive read from the walk-forward belief before converging; flat staking loses more
      slowly but just as surely.
    </p>
    <div class="sub-h">Football</div>
    <div class="table-scroll">
    <table>
      <thead><tr><th>Threshold</th><th class="num">Trades</th><th class="num">Kelly CAGR</th><th class="num">Kelly final $</th><th class="num">Flat CAGR</th><th class="num">Flat final $</th></tr></thead>
      <tbody>{football_sweep_rows}</tbody>
    </table>
    </div>
    <div class="sub-h">Tennis</div>
    <div class="table-scroll">
    <table>
      <thead><tr><th>Threshold</th><th class="num">Trades</th><th class="num">Kelly CAGR</th><th class="num">Kelly final $</th><th class="num">Flat CAGR</th><th class="num">Flat final $</th></tr></thead>
      <tbody>{tennis_sweep_rows}</tbody>
    </table>
    </div>
  </section>

  <section class="panel">
    <h2>3. Same games, opposite side: {primary_threshold}% threshold head-to-head</h2>
    <p class="panel-note">
      Both charts plot quarter-Kelly equity on the identical set of matches used in the corresponding
      favorite-side report &mdash; the only thing that changes is which side of the bet is taken.
    </p>
    <div class="sub-h">Football &middot; {football_n} matches</div>
    <div class="stats">
      <div class="stat"><div class="label">Favorite side</div><div class="value" style="color:var(--series-fav)">${football_fav_final}</div><div class="sub">CAGR {football_fav_cagr}%</div></div>
      <div class="stat"><div class="label">Longshot side</div><div class="value" style="color:var(--series-dog)">${football_dog_final}</div><div class="sub">CAGR {football_dog_cagr}%</div></div>
    </div>
    <div class="legend">
      <span><span class="swatch" style="background:var(--series-fav)"></span>Favorite</span>
      <span><span class="swatch" style="background:var(--series-dog)"></span>Longshot</span>
    </div>
    <div class="chart-block" id="chart-football"></div>

    <div class="sub-h">Tennis &middot; {tennis_n} matches</div>
    <div class="stats">
      <div class="stat"><div class="label">Favorite side</div><div class="value" style="color:var(--series-fav)">${tennis_fav_final}</div><div class="sub">CAGR {tennis_fav_cagr}%</div></div>
      <div class="stat"><div class="label">Longshot side</div><div class="value" style="color:var(--series-dog)">${tennis_dog_final}</div><div class="sub">CAGR {tennis_dog_cagr}%</div></div>
    </div>
    <div class="legend">
      <span><span class="swatch" style="background:var(--series-fav)"></span>Favorite</span>
      <span><span class="swatch" style="background:var(--series-dog)"></span>Longshot</span>
    </div>
    <div class="chart-block" id="chart-tennis"></div>
  </section>

  <footer>
    Same data and engines as the favorite-side reports: football-data.co.uk and tennis-data.co.uk closing
    lines, unmodified <code>run_sim</code> / <code>run_flat_sim</code> from the Polymarket Final-1% project.
    The only change: <code>src/football_favorite_bias.py</code> and <code>src/tennis_favorite_bias.py</code>
    now take a <code>side="favorite"|"longshot"</code> parameter, with match selection always keyed to the
    favorite crossing the threshold, so favorite and longshot backtests are directly comparable. Full numbers:
    <code>results/underdog_bias/underdog_bias_results.json</code>.
  </footer>
</div>

<div class="tooltip" id="tooltip"></div>

<script>
function renderChart(containerId, favSeries, dogSeries) {{
  const container = document.getElementById(containerId);
  const width = container.clientWidth || 900;
  const height = 280;
  const pad = {{ top: 16, right: 16, bottom: 28, left: 64 }};
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;

  const allVals = favSeries.concat(dogSeries).map(d => d[1]);
  const minV = Math.min(...allVals, 0);
  const maxV = Math.max(...allVals);
  const n = favSeries.length;

  const x = i => pad.left + (i / (n - 1)) * plotW;
  const y = v => pad.top + plotH - ((v - minV) / (maxV - minV || 1)) * plotH;

  function pathFor(series) {{
    return series.map((d, i) => `${{i === 0 ? 'M' : 'L'}} ${{x(i).toFixed(2)}} ${{y(d[1]).toFixed(2)}}`).join(' ');
  }}

  const gridCount = 4;
  let gridLines = '';
  let axisLabels = '';
  for (let g = 0; g <= gridCount; g++) {{
    const v = minV + (maxV - minV) * (g / gridCount);
    const yy = y(v);
    gridLines += `<line class="grid-line" x1="${{pad.left}}" x2="${{width - pad.right}}" y1="${{yy}}" y2="${{yy}}"/>`;
    axisLabels += `<text class="axis-label" x="${{pad.left - 8}}" y="${{yy + 4}}" text-anchor="end">$${{Math.round(v).toLocaleString()}}</text>`;
  }}
  const yearTicks = 3;
  for (let t = 0; t <= yearTicks; t++) {{
    const idx = Math.round((n - 1) * t / yearTicks);
    const xx = x(idx);
    axisLabels += `<text class="axis-label" x="${{xx}}" y="${{height - 6}}" text-anchor="middle">${{favSeries[idx][0].slice(0,7)}}</text>`;
  }}

  container.innerHTML = `
    <svg viewBox="0 0 ${{width}} ${{height}}" width="${{width}}" height="${{height}}">
      ${{gridLines}}
      <path d="${{pathFor(dogSeries)}}" fill="none" stroke="var(--series-dog)" stroke-width="2"/>
      <path d="${{pathFor(favSeries)}}" fill="none" stroke="var(--series-fav)" stroke-width="2"/>
      ${{axisLabels}}
      <line class="crosshair" x1="0" x2="0" y1="${{pad.top}}" y2="${{pad.top + plotH}}"/>
      <rect class="hover-rect" x="${{pad.left}}" y="${{pad.top}}" width="${{plotW}}" height="${{plotH}}" fill="transparent"/>
    </svg>
  `;

  const svg = container.querySelector('svg');
  const hoverRect = container.querySelector('.hover-rect');
  const crosshair = container.querySelector('.crosshair');
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
    const fv = favSeries[idx][1];
    const dv = dogSeries[idx][1];
    tooltip.innerHTML = `
      <div class="t-head">${{favSeries[idx][0]}}</div>
      <div class="t-row"><span class="k"><span class="swatch" style="background:var(--series-fav)"></span>Favorite</span><span>$${{fv.toLocaleString(undefined,{{maximumFractionDigits:0}})}}</span></div>
      <div class="t-row"><span class="k"><span class="swatch" style="background:var(--series-dog)"></span>Longshot</span><span>$${{dv.toLocaleString(undefined,{{maximumFractionDigits:0}})}}</span></div>
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

const footballFav = {football_fav_series_json};
const footballDog = {football_dog_series_json};
const tennisFav = {tennis_fav_series_json};
const tennisDog = {tennis_dog_series_json};

function renderAll() {{
  renderChart('chart-football', footballFav, footballDog);
  renderChart('chart-tennis', tennisFav, tennisDog);
}}
renderAll();
window.addEventListener('resize', renderAll);
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
