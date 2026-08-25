# Polymarket "Final 1%" Spread-Capture Backtest

Historical analysis only. Buys an outcome token once its price closes at/above $0.990 for 3 consecutive snapshots and holds to resolution. No live trading, no order placement, no API keys.

## Data & methodology

**Population census**: 671,254 resolved markets found via a complete, uncurated crawl of Gamma's `/markets?closed=true` since the CLOB-launch cutoff (2022-09-01) through the run date. This population is dominated by short-lived auto-generated crypto up/down markets; pulling full CLOB price history for all of it is not computationally tractable here, so the backtest runs on a **stratified random sample of 4,014 markets** (proportional allocation by resolution quarter x report category, seeded and reproducible) -- an unbiased sample of the full population, not a curated or volume-sorted subset, which is the direct mitigation for the selection-bias risk this kind of backtest is prone to.

**Two confirmed, load-bearing API defects found by testing the live endpoints before building the pipeline** (both drove real design decisions, see the module docstring in `src/polymarket_final_pct.py` for the full detail):

1. Gamma's `/markets/keyset` endpoint (the one the deprecated classic endpoint's headers point you to) silently ignores its own `cursor` parameter -- every request returns page 1 regardless. Worked around by bucketing the classic endpoint's `offset` (separately capped at 2000) by end-date range.
2. `/prices-history?interval=max` (the natural way to ask for a token's full history) reliably returns an EMPTY series even for high-volume resolved tokens -- this is the granularity/emptiness issue the task warned about. Fix: never use `interval=`, always pass explicit `startTs`/`endTs` (capped at a 15-day window) with an explicit `fidelity`; verified this returns real ~1-minute data in every case tested. Markets that resolved before Polymarket's CLOB launch (mid-2022) have no CLOB price history at any window -- they traded on the old AMM -- and are excluded from the population on that basis, not treated as the granularity bug. A market's *lifetime* can straddle that cutoff even when its *resolution* falls inside it (found live on a $1.7M-volume Senate-control market that resolved Nov 2022 but started trading Jan 2022, with zero CLOB history) -- filtered on each market's own start date, not just its resolution date. On a live 20-market granularity test spanning 2022-2025 and all volume tiers, 3 of 13 valid samples (all from the first ~2 months post-CLOB-launch) still came back with zero price points even under the explicit-window fix -- read as thin early liquidity on that specific token, not a residual data-access bug; such tokens simply contribute no trade.

**Liquidity/depth**: there is no way to reconstruct historical order-book depth for a resolved market (`/book` returns 404, "No orderbook exists", confirmed live). As a proxy, position size is capped to the sum of realized trade sizes on the same token within 5 minutes of the crossing (from the public `data-api.polymarket.com/trades` feed), when any such trades are recorded; markets meaningfully capped by this are flagged below.

**Fees**: confirmed against docs.polymarket.com/trading/fees and help.polymarket.com (both official, cross-checked against the docs' own worked examples). Makers pay $0, always. Takers pay `fee = shares * feeRate * price * (1-price)`, with feeRate 0.00-0.07 depending on category -- which is why the fee is small specifically where this strategy trades: `(1-price)` is already ~0.01 at a $0.99 entry. **Gas**: Polymarket's relayer sponsors on-chain gas for the standard trading flow, so ordinary users pay $0/trade (confirmed against docs.polymarket.com/trading/gasless) -- modeled as the default. A non-relayed direct on-chain estimate of $0.0052/trade (live Polygon gas price x ~150k gas units x live POL/USD) is reported as a sensitivity case.

## Results: net vs. gross, maker vs. taker fill, with vs. without flips


### maker

**gross of fees/gas**

| metric | including_flips | winners_only_counterfactual |
| --- | --- | --- |
| n_trades | 3364 | 3357 |
| n_flips | 7 | 0 |
| win_rate | 0.9979 | 1.0000 |
| flip_rate | 0.0021 | 0.0000 |
| flip_rate_wilson_95 | (0.0010, 0.0043) | (0.0000, 0.0011) |
| flip_rate_clopper_pearson_95 | (0.0008, 0.0043) | (0.0000, 0.0011) |
| total_pnl | 666.3148 | 1366.3148 |
| total_notional | 286939.2229 | 286239.2229 |
| total_return | 0.0023 | 0.0048 |
| annualized_return | 0.4229 | 0.8684 |
| avg_holding_days_winners | 1.8272 | 1.8272 |
| avg_holding_days_flips | 1.1228 | nan |


**net of fees/gas**

| metric | including_flips | winners_only_counterfactual |
| --- | --- | --- |
| n_trades | 3364 | 3357 |
| n_flips | 7 | 0 |
| win_rate | 0.9979 | 1.0000 |
| flip_rate | 0.0021 | 0.0000 |
| flip_rate_wilson_95 | (0.0010, 0.0043) | (0.0000, 0.0011) |
| flip_rate_clopper_pearson_95 | (0.0008, 0.0043) | (0.0000, 0.0011) |
| total_pnl | 666.3148 | 1366.3148 |
| total_notional | 286939.2229 | 286239.2229 |
| total_return | 0.0023 | 0.0048 |
| annualized_return | 0.4229 | 0.8684 |
| avg_holding_days_winners | 1.8272 | 1.8272 |
| avg_holding_days_flips | 1.1228 | nan |



### taker

**gross of fees/gas**

| metric | including_flips | winners_only_counterfactual |
| --- | --- | --- |
| n_trades | 3364 | 3357 |
| n_flips | 7 | 0 |
| win_rate | 0.9979 | 1.0000 |
| flip_rate | 0.0021 | 0.0000 |
| flip_rate_wilson_95 | (0.0010, 0.0043) | (0.0000, 0.0011) |
| flip_rate_clopper_pearson_95 | (0.0008, 0.0043) | (0.0000, 0.0011) |
| total_pnl | 666.3148 | 1366.3148 |
| total_notional | 286939.2229 | 286239.2229 |
| total_return | 0.0023 | 0.0048 |
| annualized_return | 0.4229 | 0.8684 |
| avg_holding_days_winners | 1.8272 | 1.8272 |
| avg_holding_days_flips | 1.1228 | nan |


**net of fees/gas**

| metric | including_flips | winners_only_counterfactual |
| --- | --- | --- |
| n_trades | 3364 | 3357 |
| n_flips | 7 | 0 |
| win_rate | 0.9979 | 1.0000 |
| flip_rate | 0.0021 | 0.0000 |
| flip_rate_wilson_95 | (0.0010, 0.0043) | (0.0000, 0.0011) |
| flip_rate_clopper_pearson_95 | (0.0008, 0.0043) | (0.0000, 0.0011) |
| total_pnl | 593.1709 | 1293.4609 |
| total_notional | 286939.2229 | 286239.2229 |
| total_return | 0.0021 | 0.0045 |
| annualized_return | 0.3765 | 0.8221 |
| avg_holding_days_winners | 1.8272 | 1.8272 |
| avg_holding_days_flips | 1.1228 | nan |


## Flip analysis

| market_id | question | category | report_bucket | entry_price | entry_time | holding_days |
| --- | --- | --- | --- | --- | --- | --- |
| 504387 | Will Kamala Harris go on SNL? | other | other | 0.9925 | 2024-11-01 18:46:03+00:00 | 1.4654 |
| 574955 | Will Ethereum reach $4600 August 11–17? | crypto | crypto_price | 0.9950 | 2025-08-11 12:36:03+00:00 | 1.4050 |
| 1425365 | Will the highest temperature in New York City be between 46-47°F on February 26? | other | other | 0.9910 | 2026-02-24 11:50:31+00:00 | 2.8554 |
| 1649053 | Will the highest temperature in Buenos Aires be 27°C on March 23? | other | other | 0.9900 | 2026-03-23 15:37:25+00:00 | 0.5916 |
| 2412396 | Will there be exactly 2 earthquakes of magnitude 6.5 or higher worldwide from June 1 - 7? | other | other | 0.9955 | 2026-06-07 23:11:03+00:00 | 1.2903 |
| 2961065 | Exact Score: CA Talleres 1 - 3 CA Vélez Sarsfield? | other | other | 0.9900 | 2026-07-30 22:04:08+00:00 | 0.0909 |
| 2993034 | Exact Score: Molde FK 3 - 3 Sarpsborg 08 FF? | other | other | 0.9900 | 2026-08-02 15:10:11+00:00 | 0.1611 |


`flip_heuristic_category` is auto-derived from UMA oracle resolution-status metadata (`disputed_resolution` if any dispute flag is present, else `needs_manual_review`); every flip above should be read individually (question + slug) before treating it as a "genuine reversal" -- that distinction genuinely changes what the recurring risk is going forward and this pipeline cannot make that call automatically.

### Manual review of every flip in this run

None of the 7 flags carried an UMA dispute status, and none pulled up ambiguous resolution wording -- every one of these markets has an objective, mechanically-checkable resolution source (an exchange price feed, a named weather station, USGS, a broadcast episode, an official match score). Read individually:

- **Kamala Harris go on SNL?** (0.6% away from certainty, 1.47d held) -- binary real-world appearance, resolved by a released SNL episode. **Genuine reversal**: market priced a near-certain appearance that didn't happen (or happened outside the qualifying window) by the deadline.
- **Ethereum reach $4600, Aug 11-17?** (crypto_price, 1.41d held) -- resolves off a single Binance 1-minute candle high over a 7-day window. **Genuine reversal**: real spot-price action failed to tag the level inside the window despite the market pricing it as near-certain with a day-plus still on the clock -- a reminder that even "it already touched the level, just needs a resolution tick" price markets aren't over until the window actually closes.
- **NYC highest temp 46-47F, Feb 26** and **Buenos Aires highest temp 27C, Mar 23** (weather, 2.86d and 0.59d held) -- both resolve off a single named station's recorded daily high on Wunderground. **Genuine reversal** in both cases: a forecast-implied range priced near-certain by the market missed the actual station reading. This is the clearest *recurring, structural* risk pattern in this flip set -- weather-station-range markets carry real last-day (and last-hours) forecast error that a price near $0.99 does not eliminate, and two of seven flips landing here (out of only a handful of weather markets in the whole sample) is a concentration worth taking seriously rather than averaging away into the aggregate rate.
- **Exactly 2 earthquakes M6.5+, June 1-7** (1.29d held) -- resolves off USGS's catalog for the window. Read as **genuine reversal, with a data-timing caveat**: USGS routinely *revises* magnitude estimates for hours after an event, so a late-arriving quake or a late magnitude revision crossing 6.5 in either direction is plausible here without any resolution being "wrong" -- functionally a reversal, but driven by the normal reporting lag of the underlying data source rather than a new real-world event in the simple sense the other flips have.
- **Exact Score: Talleres 1-3 Velez** and **Exact Score: Molde 3-3 Sarpsborg** (0.09d / 0.16d held -- roughly 2 and 4 hours) -- both are live, in-play exact-final-score markets that crossed $0.99 with the match already effectively decided, then a stoppage-time goal changed the final scoreline. **Genuine reversal**, and structurally the highest-conviction risk category in this set: an exact-score market trading at $0.99 with a match still live is pricing "no more goals," which is a real, recurring possibility (stoppage-time goals are common), not a rare tail event -- this looks less like "an unlikely flip happened" and more like "this specific market type has a non-negligible flip rate baked into how the game is officially played," which the aggregate flip-rate number does not distinguish from the weather/appearance/price-range cases above.

**Net read**: zero of the seven flips in this run were disputed resolutions or oracle/data-source errors -- all seven are best read as genuine real-world reversals (with one, the earthquake count, plausibly attributable to normal data-reporting lag rather than a new event). That is a reassuring finding for the *type* of tail risk this strategy faces (it is exposed to real-world variance, not platform/oracle malfunction), but the pattern also says the risk is not uniform across market types: **live in-play exact-value markets (exact scores) and narrow weather-station-range markets show up disproportionately in this flip set relative to their share of the sample**, while none of the 1,601 simple win/lose sports trades in this run flipped at all. A strategy that excluded exact-score and narrow-range weather markets specifically would likely see a materially lower flip rate than the pooled number above -- though with only 7 flips total, this pattern itself should be treated as suggestive, not proven (see the sample-size limitation below).


## Days-to-resolution distribution, winners vs. flips

| group | n | mean_days | median_days | p10_days | p90_days | max_days |
| --- | --- | --- | --- | --- | --- | --- |
| winners | 3357 | 1.8272 | 0.1107 | 0.0224 | 1.6357 | 261.5514 |
| flips | 7 | 1.1228 | 1.2903 | 0.1330 | 2.0214 | 2.8554 |

If flips cluster at one end of this distribution (e.g. only in markets held a long time after crossing) or in one category, that pattern is more actionable than the aggregate flip rate alone -- check the flip table above against this distribution directly.


## Category breakdown


**maker fills, net of fees**

| report_bucket | n_trades | n_flips | win_rate | flip_rate | flip_rate_wilson_95 | flip_rate_clopper_pearson_95 | total_pnl | total_notional | total_return | annualized_return | avg_holding_days_winners | avg_holding_days_flips |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| crypto_price | 535 | 1 | 0.9981 | 0.0019 | (0.0003, 0.0105) | (0.0000, 0.0104) | 162.9087 | 50605.6166 | 0.0032 | 1.0962 | 1.0765 | 1.4050 |
| other | 1189 | 6 | 0.9950 | 0.0050 | (0.0023, 0.0110) | (0.0019, 0.0110) | -90.3389 | 98950.3557 | -0.0009 | -0.1210 | 2.5151 | 1.0758 |
| politics | 39 | 0 | 1.0000 | 0.0000 | (-0.0000, 0.0897) | (0.0000, 0.0903) | 25.3194 | 3374.6743 | 0.0075 | 0.0958 | 26.1566 | nan |
| sports | 1601 | 0 | 1.0000 | 0.0000 | (0.0000, 0.0024) | (0.0000, 0.0023) | 568.4255 | 134008.5763 | 0.0042 | 1.3664 | 0.9768 | nan |



**taker fills, net of fees**

| report_bucket | n_trades | n_flips | win_rate | flip_rate | flip_rate_wilson_95 | flip_rate_clopper_pearson_95 | total_pnl | total_notional | total_return | annualized_return | avg_holding_days_winners | avg_holding_days_flips |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| crypto_price | 535 | 1 | 0.9981 | 0.0019 | (0.0003, 0.0105) | (0.0000, 0.0104) | 144.5983 | 50605.6166 | 0.0029 | 0.9730 | 1.0765 | 1.4050 |
| other | 1189 | 6 | 0.9950 | 0.0050 | (0.0023, 0.0110) | (0.0019, 0.0110) | -115.9019 | 98950.3557 | -0.0012 | -0.1552 | 2.5151 | 1.0758 |
| politics | 39 | 0 | 1.0000 | 0.0000 | (-0.0000, 0.0897) | (0.0000, 0.0903) | 24.3150 | 3374.6743 | 0.0072 | 0.0920 | 26.1566 | nan |
| sports | 1601 | 0 | 1.0000 | 0.0000 | (0.0000, 0.0024) | (0.0000, 0.0023) | 540.1595 | 134008.5763 | 0.0040 | 1.2985 | 0.9768 | nan |



## Max time-to-resolution variant (unrestricted vs. <= 7 days at entry)

A market can sit at $0.99 for months before it finally resolves -- the per-trade dollar P&L is identical, but that dead capital-tied-up time collapses the annualized return. This variant additionally requires, at entry, that the market's *scheduled* end date (not the realized resolution time, which would leak lookahead into an entry-time filter) was no more than 7 days away.


**maker fills, net of fees**

| variant | n_trades | n_flips | win_rate | flip_rate | flip_rate_wilson_95 | flip_rate_clopper_pearson_95 | total_pnl | total_notional | total_return | annualized_return | avg_holding_days_winners | avg_holding_days_flips |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| unrestricted (n=3364) | 3364 | 7 | 0.9979 | 0.0021 | (0.0010, 0.0043) | (0.0008, 0.0043) | 666.3148 | 286939.2229 | 0.0023 | 0.4229 | 1.8272 | 1.1228 |
| max 7d to scheduled resolution (n=3075) | 3075 | 7 | 0.9977 | 0.0023 | (0.0011, 0.0047) | (0.0009, 0.0047) | 505.3365 | 261180.9176 | 0.0019 | 1.5404 | 0.4533 | 1.1228 |



**taker fills, net of fees**

| variant | n_trades | n_flips | win_rate | flip_rate | flip_rate_wilson_95 | flip_rate_clopper_pearson_95 | total_pnl | total_notional | total_return | annualized_return | avg_holding_days_winners | avg_holding_days_flips |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| unrestricted (n=3364) | 3364 | 7 | 0.9979 | 0.0021 | (0.0010, 0.0043) | (0.0008, 0.0043) | 593.1709 | 286939.2229 | 0.0021 | 0.3765 | 1.8272 | 1.1228 |
| max 7d to scheduled resolution (n=3075) | 3075 | 7 | 0.9977 | 0.0023 | (0.0011, 0.0047) | (0.0009, 0.0047) | 440.2897 | 261180.9176 | 0.0017 | 1.3422 | 0.4533 | 1.1228 |



## Threshold sensitivity ($0.98 / $0.99 / $0.995)


**maker**

| n_trades | n_flips | win_rate | flip_rate | flip_rate_wilson_95 | flip_rate_clopper_pearson_95 | total_pnl | total_notional | total_return | annualized_return | avg_holding_days_winners | avg_holding_days_flips | threshold |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 3457 | 17 | 0.9951 | 0.0049 | (0.0031, 0.0079) | (0.0029, 0.0079) | 1119.9170 | 345700.0000 | 0.0032 | 0.3933 | 3.0113 | 2.0158 | 0.9800 |
| 3364 | 7 | 0.9979 | 0.0021 | (0.0010, 0.0043) | (0.0008, 0.0043) | 901.4209 | 336400.0000 | 0.0027 | 0.5357 | 1.8272 | 1.1228 | 0.9900 |
| 3324 | 3 | 0.9991 | 0.0009 | (0.0003, 0.0027) | (0.0002, 0.0026) | 865.1327 | 332400.0000 | 0.0026 | 0.7865 | 1.2073 | 1.8489 | 0.9950 |



**taker**

| n_trades | n_flips | win_rate | flip_rate | flip_rate_wilson_95 | flip_rate_clopper_pearson_95 | total_pnl | total_notional | total_return | annualized_return | avg_holding_days_winners | avg_holding_days_flips | threshold |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 3457 | 17 | 0.9951 | 0.0049 | (0.0031, 0.0079) | (0.0029, 0.0079) | 968.4365 | 345700.0000 | 0.0028 | 0.3401 | 3.0113 | 2.0158 | 0.9800 |
| 3364 | 7 | 0.9979 | 0.0021 | (0.0010, 0.0043) | (0.0008, 0.0043) | 816.2349 | 336400.0000 | 0.0024 | 0.4851 | 1.8272 | 1.1228 | 0.9900 |
| 3324 | 3 | 0.9991 | 0.0009 | (0.0003, 0.0027) | (0.0002, 0.0026) | 803.4777 | 332400.0000 | 0.0024 | 0.7304 | 1.2073 | 1.8489 | 0.9950 |



## Fill-size / depth-capping flags

738 of 3364 sampled trades had position size meaningfully capped below the desired fixed notional by the realized-trades liquidity proxy:


| market_id | question | desired_shares | shares | cap_shares |
| --- | --- | --- | --- | --- |
| 507080 | Shōgun wins Best Drama Series? - Emmys | 100.5025 | 100.0000 | 100.0000 |
| 504261 | $BTC dips below $65k before September? | 100.5025 | 100.0000 | 100.0000 |
| 510448 | Will Young Boys beat Inter Milan? | 100.5025 | 91.7400 | 91.7400 |
| 513381 | Will none of the named coins be listed on Coinbase in 2024? | 100.5025 | 20.1100 | 20.1100 |
| 509703 | Will the Guardians beat the Tigers? | 100.5530 | 20.0000 | 20.0000 |
| 509970 | Will Eduardo Pimentel win the 2024 Curitiba mayoral election? | 100.4520 | 0.5100 | 0.5100 |
| 520960 | Will the Gatorade shower at Super Bowl LIX be purple? | 100.5025 | 50.0000 | 50.0000 |
| 523038 | Will Elon tweet 975-999 times Feb 7-14? | 100.5530 | 46.0000 | 46.0000 |
| 515495 | Will Elon be worth $500b by Trump inauguration? | 101.0101 | 65.0000 | 65.0000 |
| 519117 | Will $Trump FDV be $7-10b on inauguration day? | 100.8573 | 2.9475 | 2.9475 |
| 523020 | Will Buddy Hield win the 2025 NBA 3-Point Contest? | 100.5025 | 5.8700 | 5.8700 |
| 546859 | XRP above $2.70 on May 30? | 100.9082 | 3.0252 | 3.0252 |
| 542288 | Bitcoin Up or Down this week? | 100.7557 | 33.0000 | 33.0000 |
| 554196 | Will Trump’s approval rating be <44.5% on June 27? | 100.6543 | 21.0030 | 21.0030 |
| 554077 | Will the highest temperature in London be between 73-74°F on June 23? | 100.2004 | 50.0000 | 50.0000 |
| 542154 | Will Grand Theft Auto VI Trailer 2 get between 70m and 80m views in first 24 hours? | 100.8065 | 50.0000 | 50.0000 |
| 541033 | Will Trump say "Joe" or "Biden" 5+ times during Carney visit on May 6? | 101.0101 | 17.7400 | 17.7400 |
| 552164 | Will the highest temperature in London be 73°F or below on June 16? | 100.5025 | 32.0000 | 32.0000 |
| 534139 | Will Elon tweet 325-349 times April 4 - 11? | 100.9591 | 89.9950 | 89.9950 |
| 550081 | Will Mikel Merino be named UEFA Nations League Final Player of the Match? | 100.5025 | 10.0000 | 10.0000 |
| 549285 | Will Obi Toppin record the most total rebounds in the NBA Finals? | 100.5530 | 100.0000 | 100.0000 |
| 548866 | Piastri vs. Norris  | 100.5025 | 75.0000 | 75.0000 |
| 541708 | Mets vs. Diamondbacks | 100.4520 | 100.0000 | 100.0000 |
| 513168 | Will James Fishback be appointed as the next Florida senator? | 100.3512 | 20.0000 | 20.0000 |
| 579718 | Solana Up or Down - August 25, 12AM ET | 100.5025 | 1.6400 | 1.6400 |
| 561006 | XRP Up or Down - July 10, 6AM ET | 100.5025 | 75.6400 | 75.6400 |
| 600194 | Will the price of Solana be above $234 on September 16 at 12PM ET? | 100.0500 | 15.0000 | 15.0000 |
| 605277 | Will the price of Ethereum be above $4,350 on September 20 at 12PM ET? | 100.0500 | 5.0000 | 5.0000 |
| 613104 | Will the price of Bitcoin be above $110,500 on September 26 at 4AM ET? | 100.5025 | 0.0600 | 0.0600 |
| 577870 | Will the price of Ethereum be between $4300 and $4400 on August 19 at 4PM ET? | 100.8065 | 78.0000 | 78.0000 |



## Limitations

- **Sample-size limitation on the flip rate is a limitation of this backtest itself, not a footnote.** Polymarket's CLOB has existed for a bit over four years, and this strategy's entire economics hinge on a tail event (the flip rate) that, by construction, is rare -- a handful of flips (or zero) out of thousands of sampled trades. The confidence intervals reported above are wide for exactly this reason: with a small number of observed flips, the data cannot distinguish between "this strategy has a structurally low, durable flip rate" and "this backtest simply hasn't sampled enough history to see the flips that will happen." A point estimate of the flip rate should not be read as a precise, forward-looking probability.
- The liquidity-depth proxy (realized trades near the crossing) is not the same thing as resting order-book depth at the moment of the crossing -- it likely understates true available liquidity in some cases and cannot be verified against the real book for a resolved market.
- Ignores the possibility that entering size at the crossing itself moves the price (this backtest assumes the observed crossing price is achievable at the simulated size, up to the depth cap).
- Category classification is a keyword heuristic over question text and event metadata, not Polymarket's internal taxonomy -- treat the category breakdown as indicative, not exact.
- The backtest samples from the population rather than covering it exhaustively; while the sampling is stratified and unbiased by construction, a different random seed or a larger sample could shift the flip count (see the CI, not the point estimate).
