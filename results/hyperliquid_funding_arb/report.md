# Hyperliquid Spot-Perp Funding Arbitrage Backtest -- Report

Data source: Hyperliquid public `/info` `fundingHistory` endpoint (no auth). Full history pulled for BTC, ETH, SOL from each asset's first available record through the run time; all three coins first report funding on 2023-05-12 (their Hyperliquid listing date).

**Funding cadence data quirk**: Hyperliquid funding settled every 8 hours from 2023-05-12 until ~2023-06-08, then switched to hourly settlement (confirmed by inspecting the gap between consecutive raw records, not assumed). This pipeline derives the settlement cadence from the actual timestamp gaps at each point and annualizes off that, so it is correct across the regime switch without hardcoding either convention.

**Fees** (Hyperliquid Tier 0, confirmed against the docs on 2026-08-25): perp maker 0.015% / taker 0.045%, spot maker 0.040% / taker 0.070%. Slippage assumed at 2.0 bps per leg (configurable).

**Breakeven derivation**: round-trip cost = 2 x (spot fee + perp fee + 2 x slippage per leg). Amortized over a 24h assumed minimum holding horizon (configurable) to get a breakeven *hourly* rate, then annualized (x8760). Maker-fill breakeven: 69.35% annualized. Taker-fill breakeven: 113.15% annualized. Entry requires the observed annualized funding rate to exceed 2.0x breakeven (configurable buffer).

## Results summary

| asset_or_variant | fill_type | holding_variant | n_hours | years | total_return_gross | total_return_net | annualized_return_gross | annualized_return_net | sharpe_net | max_drawdown_net | pct_hours_in_position | n_trades | avg_holding_hours | total_fee_drag_frac |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| BTC | maker | uncapped | 28267 | 3.2268 | 0.0365 | -0.0300 | 0.0113 | -0.0093 | -2.0640 | -0.0305 | 0.0092 | 35 | 7.4000 | 0.0665 |
| ETH | maker | uncapped | 28267 | 3.2268 | 0.0168 | -0.0478 | 0.0052 | -0.0148 | -3.4235 | -0.0478 | 0.0048 | 34 | 4.0294 | 0.0646 |
| SOL | maker | uncapped | 28267 | 3.2268 | 0.1255 | -0.0094 | 0.0389 | -0.0029 | -0.4358 | -0.0304 | 0.0285 | 71 | 11.3521 | 0.1349 |
| ROTATION | maker | uncapped | 28267 | 3.2268 | 0.1468 | -0.0850 | 0.0455 | -0.0263 | -2.8786 | -0.0873 | 0.0336 | 122 | 7.7951 | 0.2318 |
| BTC | maker | capped_24h | 28267 | 3.2268 | 0.0354 | -0.0349 | 0.0110 | -0.0108 | -2.3475 | -0.0353 | 0.0089 | 37 | 6.8108 | 0.0703 |
| ETH | maker | capped_24h | 28267 | 3.2268 | 0.0168 | -0.0478 | 0.0052 | -0.0148 | -3.4235 | -0.0478 | 0.0048 | 34 | 4.0294 | 0.0646 |
| SOL | maker | capped_24h | 28267 | 3.2268 | 0.1218 | -0.0226 | 0.0378 | -0.0070 | -1.0230 | -0.0328 | 0.0274 | 76 | 10.1974 | 0.1444 |
| ROTATION | maker | capped_24h | 28267 | 3.2268 | 0.1445 | -0.0911 | 0.0448 | -0.0282 | -3.0816 | -0.0934 | 0.0329 | 124 | 7.5081 | 0.2356 |
| BTC | taker | uncapped | 28267 | 3.2268 | 0.0094 | -0.0061 | 0.0029 | -0.0019 | -0.6829 | -0.0072 | 0.0014 | 5 | 8.0000 | 0.0155 |
| ETH | taker | uncapped | 28267 | 3.2268 | 0.0018 | -0.0137 | 0.0005 | -0.0043 | -1.5853 | -0.0137 | 0.0005 | 5 | 2.6000 | 0.0155 |
| SOL | taker | uncapped | 28267 | 3.2268 | 0.0323 | -0.0297 | 0.0100 | -0.0092 | -1.6571 | -0.0347 | 0.0053 | 20 | 7.4500 | 0.0620 |
| ROTATION | taker | uncapped | 28267 | 3.2268 | 0.0411 | -0.0364 | 0.0127 | -0.0113 | -1.8152 | -0.0414 | 0.0066 | 25 | 7.4800 | 0.0775 |
| BTC | taker | capped_24h | 28267 | 3.2268 | 0.0091 | -0.0095 | 0.0028 | -0.0029 | -0.9856 | -0.0095 | 0.0014 | 6 | 6.5000 | 0.0186 |
| ETH | taker | capped_24h | 28267 | 3.2268 | 0.0018 | -0.0137 | 0.0005 | -0.0043 | -1.5853 | -0.0137 | 0.0005 | 5 | 2.6000 | 0.0155 |
| SOL | taker | capped_24h | 28267 | 3.2268 | 0.0323 | -0.0297 | 0.0100 | -0.0092 | -1.6571 | -0.0347 | 0.0053 | 20 | 7.4500 | 0.0620 |
| ROTATION | taker | capped_24h | 28267 | 3.2268 | 0.0408 | -0.0398 | 0.0127 | -0.0123 | -1.9533 | -0.0447 | 0.0066 | 26 | 7.1538 | 0.0806 |


## Illiquidity / persistence flags

Runs where the raw hourly funding rate stayed one-directional for 2+ weeks. Real capital would likely have compressed a rate that persisted this long, or the imbalance itself reflects limited liquidity at size -- this backtest assumes fills at the historical rate/notional with zero market impact, so returns during these windows are probably overstated.


**BTC**

| start | end | direction | run_hours | run_days | mean_annualized_rate |
| --- | --- | --- | --- | --- | --- |
| 2023-10-19 13:00:00.010000+00:00 | 2023-11-16 11:00:00.034000+00:00 | positive | 670.0000 | 27.9167 | 0.3538 |
| 2023-12-06 14:00:00.224000+00:00 | 2024-01-15 20:00:00.083000+00:00 | positive | 966.0000 | 40.2500 | 0.4566 |
| 2024-02-06 23:00:00.019000+00:00 | 2024-03-20 07:00:00.143000+00:00 | positive | 1016.0000 | 42.3333 | 0.5597 |
| 2024-03-20 12:00:00.024000+00:00 | 2024-04-15 21:00:00.363000+00:00 | positive | 633.0001 | 26.3750 | 0.3651 |
| 2024-05-21 16:00:00.017000+00:00 | 2024-06-23 21:00:00.087000+00:00 | positive | 797.0000 | 33.2083 | 0.2282 |
| 2024-07-12 12:00:00.147000+00:00 | 2024-08-07 15:00:00.181000+00:00 | positive | 627.0000 | 26.1250 | 0.1590 |
| 2024-09-18 11:00:00.103000+00:00 | 2024-10-10 18:00:00.120000+00:00 | positive | 535.0000 | 22.2917 | 0.1663 |
| 2024-10-25 09:00:00.001000+00:00 | 2024-12-23 05:00:00.445000+00:00 | positive | 1412.0001 | 58.8333 | 0.3101 |
| 2024-12-24 21:00:00.590000+00:00 | 2025-01-15 02:00:00.002000+00:00 | positive | 508.9998 | 21.2083 | 0.1494 |
| 2025-07-02 21:00:00.024000+00:00 | 2025-08-01 19:00:00.069000+00:00 | positive | 718.0000 | 29.9167 | 0.1996 |
| 2025-08-30 07:00:00.005000+00:00 | 2025-09-17 03:00:00.013000+00:00 | positive | 428.0000 | 17.8333 | 0.1072 |
| 2025-11-09 03:00:00.067000+00:00 | 2025-11-24 03:00:00.010000+00:00 | positive | 360.0000 | 15.0000 | 0.1056 |
| 2026-07-01 07:00:00.022000+00:00 | 2026-07-20 18:00:00.027000+00:00 | positive | 467.0000 | 19.4583 | 0.1079 |



**ETH**

| start | end | direction | run_hours | run_days | mean_annualized_rate |
| --- | --- | --- | --- | --- | --- |
| 2023-05-31 16:00:00.323000+00:00 | 2023-06-17 23:00:00.314000+00:00 | positive | 415.0000 | 17.2917 | 0.4115 |
| 2023-06-21 11:00:00.035000+00:00 | 2023-07-08 07:00:00.053000+00:00 | positive | 404.0000 | 16.8333 | 0.4550 |
| 2023-10-23 20:00:00.204000+00:00 | 2023-11-21 15:00:00.354000+00:00 | positive | 691.0000 | 28.7917 | 0.4520 |
| 2023-11-28 07:00:00.074000+00:00 | 2024-01-20 17:00:00.316000+00:00 | positive | 1282.0001 | 53.4167 | 0.4263 |
| 2024-02-24 19:00:00.350000+00:00 | 2024-03-20 09:00:00.369000+00:00 | positive | 590.0000 | 24.5833 | 0.6187 |
| 2024-03-20 15:00:00.330000+00:00 | 2024-04-14 20:00:00.338000+00:00 | positive | 605.0000 | 25.2083 | 0.2880 |
| 2024-05-16 03:00:00.085000+00:00 | 2024-06-19 12:00:00.056000+00:00 | positive | 825.0000 | 34.3750 | 0.2873 |
| 2024-06-19 14:00:00.097000+00:00 | 2024-07-04 08:00:00.078000+00:00 | positive | 354.0000 | 14.7500 | 0.1647 |
| 2024-07-16 09:00:00.120000+00:00 | 2024-08-01 07:00:00.151000+00:00 | positive | 382.0000 | 15.9167 | 0.1849 |
| 2024-11-05 03:00:00.067000+00:00 | 2024-12-19 17:00:00.004000+00:00 | positive | 1070.0000 | 44.5833 | 0.4304 |
| 2024-12-23 09:00:00.147000+00:00 | 2025-01-09 13:00:00.013000+00:00 | positive | 412.0000 | 17.1667 | 0.1276 |
| 2025-07-02 22:00:00.038000+00:00 | 2025-07-29 14:00:00.116000+00:00 | positive | 640.0000 | 26.6667 | 0.2443 |
| 2025-11-12 18:00:00.036000+00:00 | 2025-11-29 06:00:00.061000+00:00 | positive | 396.0000 | 16.5000 | 0.1006 |
| 2025-12-06 04:00:00.025000+00:00 | 2025-12-26 02:00:00.062000+00:00 | positive | 478.0000 | 19.9167 | 0.1017 |
| 2026-01-04 17:00:00.020000+00:00 | 2026-01-19 23:00:00.040000+00:00 | positive | 366.0000 | 15.2500 | 0.1016 |
| 2026-06-30 14:00:00.043000+00:00 | 2026-07-22 21:00:00.034000+00:00 | positive | 535.0000 | 22.2917 | 0.1074 |



**SOL**

| start | end | direction | run_hours | run_days | mean_annualized_rate |
| --- | --- | --- | --- | --- | --- |
| 2023-11-02 09:00:00.092000+00:00 | 2023-11-30 19:00:00.053000+00:00 | positive | 682.0000 | 28.4167 | 0.5185 |
| 2023-11-30 21:00:00.403000+00:00 | 2023-12-18 03:00:00.150000+00:00 | positive | 413.9999 | 17.2500 | 0.6701 |
| 2023-12-18 08:00:00.067000+00:00 | 2024-01-03 12:00:00.201000+00:00 | positive | 388.0000 | 16.1667 | 0.9660 |
| 2024-02-05 22:00:00.193000+00:00 | 2024-03-19 02:00:00.414000+00:00 | positive | 1012.0001 | 42.1667 | 0.7891 |
| 2024-03-19 08:00:00.152000+00:00 | 2024-04-05 08:00:00.148000+00:00 | positive | 408.0000 | 17.0000 | 0.4778 |
| 2024-05-21 01:00:00.022000+00:00 | 2024-06-16 00:00:00.002000+00:00 | positive | 623.0000 | 25.9583 | 0.2689 |
| 2024-09-18 12:00:00.099000+00:00 | 2024-12-19 18:00:00.081000+00:00 | positive | 2214.0000 | 92.2500 | 0.3068 |
| 2025-07-09 15:00:00.009000+00:00 | 2025-07-29 14:00:00.116000+00:00 | positive | 479.0000 | 19.9583 | 0.2766 |



## Caveats

- Ignores basis/premium P&L from the spot-perp price convergence; assumes a perfectly delta-neutral hedge, only the funding differential is modeled.
- The 'reverse when funding is negative' leg (short spot / long perp) assumes short-spot exposure is available at the modeled spot fee with no separate borrow cost -- Hyperliquid spot itself has no native margin/short, so in practice this leg needs a borrow facility whose cost is not modeled here.
- No market impact / depth modeling: fills assumed at the historical funding rate and full requested notional regardless of size.
- The volatility-adjusted sizer (see `vol_adjusted_sizer`) is illustrative only, using trailing volatility of the funding signal itself as a proxy since this pipeline does not fetch spot price history.
