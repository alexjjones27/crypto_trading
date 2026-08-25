# EGARCH implementation audit

Scope: EGARCH math only, per request. No changes made to gamma regime logic,
backtest, or strategy rules. Evidence-gathering script: `scripts/audit_egarch.py`
(one-off, not part of the pipeline).

## 0. Preliminary: there is no custom EGARCH implementation in this codebase

Before anything else: `grep -rn "log_variance\|recursion\|loglikelihood" src/`
and a full read of `models/egarch.py` and `models/walk_forward.py` confirm the
codebase contains **zero hand-rolled EGARCH math**. Every fit and forecast goes
through `arch_model(..., vol="EGARCH", p=1, o=1, q=1, dist=...)` from the
`arch` package (v8.0.0) directly. There is no separate "our implementation" to
check against a reference — `arch` **is** what's running.

This reframes items 1-2 below: instead of comparing a custom implementation
against `arch`, I independently re-derived the EGARCH(1,1) recursion from the
textbook formula in plain numpy (not copied from `arch`'s source) and compared
its output against `arch`'s actual `conditional_volatility` on the same data.
Agreement between two independently-written implementations of the same math
is the correct way to validate that `arch`'s internals do what they claim.

## 1. Model specification: confirmed against `arch`'s source

Read `arch/univariate/volatility.py` (class `EGARCH`) and the actual runtime
recursion in `arch/univariate/recursions_python.py::egarch_recursion_python`
(JIT-compiled, this is what executes — not just docs).

**Recursion, exactly as implemented (p=o=q=1):**
```
ln(sigma2_t) = omega + alpha*(|z_{t-1}| - sqrt(2/pi)) + gamma*z_{t-1} + beta*ln(sigma2_{t-1})
z_t = resid_t / sqrt(sigma2_t)
```
This matches the formula in the task description term-for-term. `sigma2_t` is
variance; `z_t` is standardized by `sqrt(sigma2_t)` (**std dev, not variance**)
— confirmed directly in source: `std_resids[t] = resids[t] / np.sqrt(sigma2[t])`
(recursions_python.py:392). The single-most-common bug class the task named
(mixing sigma vs sigma^2 in the recursion or standardization) is **not present**.

**E|z_{t-1}| constant — this is where it gets interesting.** Source line 40:
```python
SQRT2_OV_PI = 0.79788456080286541  # E[abs(e)], e~N(0,1)
```
This constant is **hardcoded** in the recursion and used **unconditionally**,
regardless of `dist=`. `EGARCH.compute_variance()` takes no distribution
argument at all — the variance recursion is structurally distribution-agnostic
in `arch`'s architecture; only the *likelihood* (used for parameter estimation)
is distribution-specific. So when fitting with `dist='t'` or `dist='skewt'`,
the alpha-term centering constant is still the Normal E|z| = 0.7979, not the
true t/skew-t E|z|.

This is **exactly the bug pattern the task asked me to check for**. Verified
the true value differs materially: for the checkpoint-2 in-sample fit
(nu=7.02), true E|z| for a standardized t(7.02) is **0.7594** vs the Normal's
0.7979 — a 5.1% difference (closed-form derivation cross-checked against 2M
Monte Carlo draws from `arch`'s own `StudentsT.simulate`: 0.7603 empirical,
matches). **Whether this actually biases anything is answered empirically in
§2 below — it doesn't, and here's why algebraically first:** the recursion is
```
ln(sigma2_t) = (omega - alpha*c) + alpha*|z_{t-1}| + gamma*z_{t-1} + beta*ln(sigma2_{t-1})
```
`c` only ever appears bundled with `omega` into a single effective intercept.
Since `omega` is freely estimated by MLE, whatever `c` is used gets exactly
compensated for in the fitted `omega` — the *dynamics* (alpha, beta, gamma)
and the resulting sigma_t path are invariant to which `c` you pick, as long as
`omega` is refit each time (which it always is here — see §3). This is
confirmed empirically, not just argued, in §2/§3.

**Likelihood correctly matches the assumed distribution** (`arch/univariate/distribution.py`):
`StudentsT.loglikelihood` implements the properly-scaled standardized-t density
(the `(nu-2)` variance-normalization term is present), and `SkewStudent.loglikelihood`
implements Hansen (1994)'s skew-t density. Neither silently falls back to
Gaussian. This directly addresses the task's item-3 concern.

**Leverage sign convention**, checked against the actual fitted data
(nu='t' fit, checkpoint-2 in-sample sample): fitted `gamma[1] = -0.1198`.
Holding alpha/beta/omega fixed, a -3-sigma shock contributes `+0.637` to
ln(sigma2) vs `-0.081` for a +3-sigma shock of the same size — i.e. **bad news
increases vol more than good news of equal magnitude, the standard equity
leverage effect, confirmed directionally correct** for this asset and this
sign convention. (Note: with `arch`'s convention, a *negative* gamma is what
produces the leverage effect — the opposite sign would mean positive shocks
raise vol more, which would be the wrong direction for equities.)

## 2. Verification against a reference implementation — comparison numbers

Independently wrote `from_scratch_egarch11()` in `scripts/audit_egarch.py`
from the textbook formula (not copied from `arch`), fit EGARCH(1,1)/t on the
same in-sample SPX series (1990-01-03 to 2017-12-29, n=7055) `arch` fit, fed
it `arch`'s own estimated (omega, alpha, gamma, beta) and backcast value, and
compared the resulting sigma_t path to `arch`'s `conditional_volatility`:

| | correlation | mean abs % diff | max abs % diff |
|---|---|---|---|
| From-scratch recursion (arch's own sqrt(2/pi) constant) vs arch | **0.998601** | **0.1417%** | 89.60% |

The max is misleading in isolation — investigated it directly: **all 65
observations with >1% divergence fall in indices 0-64 (1990-01-03 to
1990-04-04), the first ~2 months of the sample.** This is a burn-in artifact:
my from-scratch implementation's backcast/initialization convention for the
gamma-term at t=0 (z_{t-1}=0) differs slightly from `arch`'s internal one, and
with beta=0.986 persistence, that initial discrepancy decays geometrically.
By index 100: 0.17% diff. By index 200: 0.00003%. By index 500: 1.5e-16
(floating-point noise floor). **From observation 100 onward (98.6% of the
sample), mean divergence is 0.00028%.** This is as close to exact agreement as
two independently-written floating-point implementations get — it confirms
`arch`'s compiled recursion is a faithful implementation of the textbook
EGARCH(1,1) formula.

**Testing the hardcoded-Normal-constant issue directly** (§1): reran the same
from-scratch recursion using the *true* t(nu=7.02) E|z| = 0.7594 instead of
0.7979, with omega algebraically reparametrized (`omega_adj = omega +
alpha*(c_true - c_normal)`) to hold the effective intercept fixed:

| | correlation | mean abs % diff | max abs % diff |
|---|---|---|---|
| From-scratch, true t-distribution E\|z\| + adjusted omega, vs arch | **0.998600** | **0.1417%** | 89.63% |

**Identical to the control (down to the 4th decimal place, same burn-in-only
divergence pattern).** This empirically confirms the algebraic argument in
§1: `arch`'s use of the Normal E|z| constant regardless of fitted distribution
has **zero effect on the fitted alpha/beta/gamma or on the resulting sigma_t
forecast path** — it's a pure, harmless reparametrization of `omega`, not a
functional bug. I want to be precise about what this claim does and doesn't
cover: it holds because `omega` is always freely re-estimated by MLE in this
codebase (true for every fit, one-shot and walk-forward). It would NOT hold if
`omega` were ever fixed/hardcoded while only alpha/beta/gamma were refit — that
code path doesn't exist here, but it's worth flagging as a latent trap if the
pipeline ever adds a "fix omega, update the rest" shortcut.

## 3. Estimation mechanics

- **Likelihood matches distribution**: confirmed in §1.
- **Convergence flag: checked in an ad hoc diagnostic during development, NOT
  checked in the production code path.** `grep -n "convergence_flag"` across
  `src/` finds it only in a docstring comment in `walk_forward.py`, never in
  an actual `if` condition. This is a real gap relative to what was asked to
  verify. **However**, I already have direct evidence from earlier debugging
  that checking it would not have been sufficient on its own: the degenerate
  fits found and fixed in checkpoint 2 (params like `beta[1]=1.000000`,
  `mu=-2.4e7`) reported `convergence_flag == 0` ("success") from scipy — the
  optimizer had genuinely converged *to a box-constraint boundary*, which
  scipy's convergence criteria don't distinguish from a good interior optimum.
  So: `convergence_flag` should still be checked as cheap defense-in-depth
  (catches outright non-convergence, e.g. hitting max iterations without even
  reaching a boundary — a different failure mode), but the sanity-bound
  mechanism already in `walk_forward.py` (plausible annualized-vol range +
  `|beta| < 0.999`) is doing real, necessary work that `convergence_flag`
  alone would not have done. This is a recommendation to add a check, not a
  report of biased output — the existing safeguard already catches the cases
  that matter.

- **Stationarity bound**: task asked to confirm `|beta| < 1` is enforced.
  Found something more specific reading `EGARCH.bounds()`
  (volatility.py:2607-2615): `arch` box-constrains `beta` to **`[0, q]`**,
  i.e. `[0, 1]` for q=1 — **not** the symmetric `(-1, 1)` the task described.
  This is a real deviation from the general theoretical minimum (EGARCH's
  log-variance formulation doesn't strictly require non-negative beta the way
  GARCH's variance formulation does), but it's `arch`'s own deliberate design
  choice, not something this codebase's usage introduces or could disable via
  the public API. Economically it's a reasonable restriction (persistent
  volatility clustering, not an oscillating one), and it explains *exactly*
  why the degenerate fits above pinned `beta[1]` at precisely 1.000000 rather
  than some arbitrary large value: they hit this upper bound. Worth knowing,
  not worth treating as a bug.

- **Re-estimated at each walk-forward step**: confirmed by re-reading
  `walk_forward.py:115-144` fresh. `train = r.iloc[lo:t]` is strictly `[0, t)`
  — no same-day contamination. With `refit_frequency=1` (what checkpoint 2's
  actual production run used), `need_refit` is `True` on every iteration, so
  `am.fit()` (full MLE re-optimization) runs every single day, not a stale
  rolled-forward recursion. The `.fix()` path (reuse last params, cheap
  re-evaluation) only activates when `refit_frequency > 1`, which is supported
  by the code but wasn't used for the actual checkpoint-2 results.

## 4. Forecast step

- **Horizon>1 analytic forecasting**: tested directly —
  `res.forecast(horizon=5, reindex=False, method="analytic")` **raises
  `ValueError: Analytic forecasts not available for horizon > 1`**. `arch`
  itself refuses to do what the task warned against (plugging E[z]=0 forward
  and calling it a forecast) — it hard-errors instead of silently producing a
  biased multi-step number. This codebase only ever calls
  `forecast(horizon=1, ...)` (confirmed: `grep -n "horizon=" src/` finds no
  instance of horizon>1 anywhere), so this restriction never bites in
  practice, and no simulation-based multi-step method is needed **because
  none is used**. Worth stating precisely why horizon=1 doesn't need the E|z|
  integration problem at all: at horizon=1, `z_{t-1}` (the input to the
  alpha/gamma terms) is *already realized* data at the forecast origin, not a
  random variable being integrated over — the E|z| subtlety only exists for
  horizon >= 2, where the recursion would need to integrate over the
  distribution of a *future* unrealized shock. So horizon=1 forecasts here are
  exact, not an approximation.
- **Variance -> vol conversion**: `walk_forward.py:147`:
  `forecasts[t] = np.sqrt(var_pct2) / RETURN_SCALE`. Verified `fc.variance`
  is genuinely in variance units (not log-variance) by direct inspection: for
  a fit ending 2014-12-31, `fc.variance.iloc[-1,0] = 0.732` and
  `res.conditional_volatility.iloc[-1]**2 = 0.571` (same order of magnitude,
  one step apart as expected). `sqrt()` is the correct conversion; no
  malformed inverse.

## 5. Data alignment and look-ahead

- **z_{t-1}, sigma_{t-1} genuinely lagged**: confirmed in §3 (`r.iloc[lo:t]`
  is exclusive of `t`) and in §4 (forecast for day t comes from a model whose
  training data ends at `t-1`).
- **Log returns, not simple returns**: `config.py` / `data/build_dataset.py`:
  `spx_log_ret = np.log(spx_close).diff()`. Confirmed log returns throughout.
- **Mean equation**: `mean="Constant"` — verified directly that
  `res.resid == scaled_returns - res.params["mu"]` to machine precision (the
  fitted constant is what's actually subtracted before standardization, not
  a placeholder).

## 6. Verdict

**No deviation found that biases the volatility forecast.** Specifically:

| Check | Finding | Biases forecast? |
|---|---|---|
| Recursion formula | Matches textbook exactly (verified against arch's compiled recursion AND an independent numpy re-implementation, agreement to 1e-16 after burn-in) | No |
| sigma vs sigma^2 confusion | Not present — confirmed at both the recursion (std_resids uses sqrt) and forecast (fc.variance is variance, sqrt() applied correctly) layers | No |
| Normal E\|z\| constant used for t/skewt fits | Confirmed present in arch's source, confirmed hardcoded regardless of dist= | **No — empirically proven to be absorbed entirely by omega (§2), given omega is always freely refit here (§3)** |
| Likelihood distribution match | Correct t/skew-t densities, not Gaussian | No |
| Leverage sign | Correctly negative, correctly means "bad news raises vol more" for this fit | No |
| convergence_flag | Not checked in production code | **Gap, but not a demonstrated source of bias** — the sanity-bound safeguard already catches what mattered (see §3); recommend adding it anyway as cheap defense-in-depth |
| beta bounds | arch enforces [0,1], not the theoretical (-1,1) | Explains observed boundary-pinning behavior; not a bug, a design choice outside this codebase's control |
| Multi-step forecast E[z]=0 trap | Doesn't apply — arch hard-errors on horizon>1 analytic, and the codebase only ever requests horizon=1 (which is exact, not approximate) | No |
| Data alignment / look-ahead | Confirmed strictly lagged at every layer checked | No |

**The EGARCH engine is trustworthy as-is.** It should **not** be replaced with
a direct from-scratch implementation — that would mean re-deriving and
re-testing exactly the machinery this audit just spent its effort validating
against an independent implementation, for a package (`arch`) that is
peer-used, and whose only identified deviation from the naive textbook
formula (the E|z| constant) is provably inert given how this codebase uses it.

**The one actionable item is the convergence_flag gap in §3** — cheap to add,
real defense-in-depth against a *different* failure mode than the one already
guarded against, but not something with demonstrated impact on the checkpoint
2 results, which were already validated by the sanity-bound mechanism (that
mechanism's necessity and effectiveness is itself documented with before/after
evidence in `walk_forward.py`'s docstring and the checkpoint-2 commit history).

No changes made to `src/` as part of this audit, per instructions. Evidence
script (`scripts/audit_egarch.py`) is included for reproducibility but is not
wired into the pipeline.
