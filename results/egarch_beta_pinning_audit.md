# EGARCH beta boundary-pinning diagnostic

Instrumented re-run of the exact production walk-forward (expanding window,
skew-t, min_obs=500, daily refit, 1990-01-03 to 2026-08-24, n=8727 windows)
logging the raw `beta[1]` estimate for every single window, not just
aggregated accept/reject counts. Script: `scripts/audit_beta_pinning.py`.
Full per-window log: `data/processed/egarch_beta_pinning_log.csv`.

Pin threshold: `beta >= 0.9999` (essentially at `arch`'s `[0,1]` box
constraint upper bound — see the EGARCH audit for why that bound exists).

## Is it clustered, or scattered?

**Clustered — overwhelmingly and exclusively.**

| | value |
|---|---|
| Overall pin rate | 78 / 8727 = 0.89% |
| Years with any pinning | **1992, 1993, 1994, 1995 only** |
| First pinned date | 1992-11-12 |
| Last pinned date | 1995-06-02 |
| Every other year (1991, 1996-2026) | **zero pins** |
| Chi-square test (observed pins/year vs uniform-across-years null) | chi2=742.8, **p=3.3e-134** |

Pin rate by year (full table in the txt report): 1992 3.5%, 1993 11.9%, 1994
10.7%, 1995 4.8%, every other one of 36 years 0.0%. The chi-square result
isn't a formality here — p=3.3e-134 is about as far from "could be
coincidence" as a statistical test produces.

**Every later high-volatility episode in the 36-year sample — 1997-98 Asian/LTCM,
2000-02 dot-com, 2008-09 GFC, 2010 flash crash, 2011 debt downgrade, 2015-16,
2018 Volmageddon, 2020 COVID crash, 2022 bear market — shows zero pinning.**
This immediately weighs against "EGARCH(1,1) doesn't handle certain kinds of
periods" as a general specification problem: it handles every other
regime-shift/crisis episode in the sample without incident.

**The GEX-covered strategy window (2011-05-02 onward, everything the gamma
regime strategy actually trades on) has zero pinning events.** The vol
forecasts feeding the regime classifier and the mean-reversion/vol-breakout
signals are not affected by this issue at all, for any date the strategy
uses.

## Is it a window-length problem?

Tested by refitting each of the 78 pinned dates at fixed window lengths
{200, 300, 500, 750, 1000, 1500} trading days ending on that date (1500 is
often clipped to whatever history is actually available that early, e.g.
~725-1369 days — noted in the actual-length columns).

| requested length | pin rate across the 78 dates |
|---|---|
| 200 | 2.6% |
| 300 | 5.1% |
| 500 | 6.4% |
| 750 | 14.1% |
| 1000 | 56.4% |
| 1500 (~max available) | **100%** |

**This is the opposite of what a length problem predicts.** If beta were
under-identified for lack of data, pinning should get LESS common as the
window grows and the MLE has more information. Instead it gets monotonically
MORE common — every one of these 78 dates pins once the window is long
enough to include most/all of the available pre-1996 history.

## Conclusion: a data problem specific to 1990-1995, not a length or specification problem

Putting the two findings together: **more data from this specific historical
window makes the identification worse, not better**, while the exact same
EGARCH(1,1) specification, using windows of comparable or greater length,
correctly identifies beta on every other calendar period in the 36-year
sample — including far more extreme volatility episodes than anything in
1990-1995.

The mechanism this points to: the 1990-mid-1995 SPX sample apparently
contains too little genuine volatility-regime variation (few sharp,
well-separated vol-clustering events) to pin down the persistence parameter
robustly. Adding more days drawn from that same low-information regime
doesn't add identifying information — it just makes the (poorly-identified)
MLE more confident in an extreme point estimate, pushing beta toward the
boundary rather than resolving it. This is a known pathology in GARCH-family
MLE: a flat or nearly-flat region of the likelihood surface along the
persistence dimension, more data from within that same flat region doesn't
sharpen the estimate, it can concentrate the optimizer's certainty in
whichever direction is favored at the margins.

This is **not** evidence the EGARCH(1,1) specification itself is wrong (it
works everywhere else, including harder periods), and it is **not** fixable
by using a longer window (that makes it worse). It is specific to what
"1990-1995 SPX daily returns" actually contain as data.

## Practical implication

The existing sanity-bound safeguard in `walk_forward.py` (reject implausible
refits, fall back to last good parameters) is doing exactly the right thing
for this specific, identified, bounded problem — and it's already confirmed
(via the year-by-year table above, and separately via the per-year
min/max annualized-vol sanity check reported when checkpoint 2 first landed
on this bound) to only ever activate in this narrow 1992-95 window, not
anywhere the strategy actually trades. No pipeline change is needed as a
result of this diagnostic; it's confirmatory, not corrective.
