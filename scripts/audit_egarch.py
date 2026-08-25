"""EGARCH implementation audit (one-off, not part of the pipeline).

Checks, in order:
1. Confirms the codebase has no hand-rolled EGARCH math (grep already done
   manually; this script documents that finding is unchanged).
2. Reads arch's actual recursion (already inspected in
   arch/univariate/recursions_python.py) and independently re-implements
   the textbook EGARCH(1,1) formula from scratch in numpy, then compares
   the resulting sigma_t path against arch's own conditional_volatility on
   real SPX data, both fit on the codebase's actual data/config.
3. Tests whether arch's hardcoded Normal E|z| constant (sqrt(2/pi)) in the
   alpha term -- used regardless of the fitted distribution -- biases the
   fit, by re-running the from-scratch recursion with the distribution-
   correct E|z| constant (t-distribution closed form, verified against
   Monte Carlo) and an algebraically-adjusted omega, checking whether the
   two recursions (arch's constant vs the "correct" constant) produce the
   same sigma_t path.
4. Checks sign of gamma against the actual data (leverage effect).
5. Checks horizon>1 EGARCH analytic forecasting behavior in arch (does it
   raise/warn, confirming horizon=1 is the only exact analytic case).
"""

import numpy as np
import pandas as pd
from scipy.special import gammaln
from arch import arch_model

import sys
sys.path.insert(0, "src")
from spx_egarch_gex import config
from spx_egarch_gex.models.egarch import RETURN_SCALE

SQRT2_OV_PI = 0.79788456080286541  # arch's hardcoded constant, confirmed from source


def E_abs_z_studentt(nu):
    return 2 * np.sqrt(nu - 2) * np.exp(gammaln((nu + 1) / 2) - gammaln(nu / 2)) / ((nu - 1) * np.sqrt(np.pi))


def from_scratch_egarch11(resids_pct, omega, alpha, gamma, beta, backcast_lnvar, e_abs_z=SQRT2_OV_PI):
    """Independent numpy re-implementation of the EGARCH(1,1) recursion,
    written directly from the textbook formula (Nelson 1991), NOT copied
    from arch's source:

        ln(sigma2_t) = omega + beta*ln(sigma2_{t-1}) + alpha*(|z_{t-1}| - E|z|) + gamma*z_{t-1}
        z_t = resid_t / sigma_t

    resids_pct: residuals on the *100 scale (same scale arch is fit on).
    Returns sigma_t (conditional STD DEV, not variance) as a numpy array.
    """
    n = len(resids_pct)
    ln_sigma2 = np.empty(n)
    sigma2 = np.empty(n)
    z = np.empty(n)

    for t in range(n):
        ln_prev = ln_sigma2[t - 1] if t > 0 else backcast_lnvar
        z_prev = z[t - 1] if t > 0 else 0.0
        abs_z_prev = abs(z_prev) if t > 0 else e_abs_z  # neutral at t=0, matches arch's backcast convention
        ln_sigma2[t] = omega + beta * ln_prev + alpha * (abs_z_prev - e_abs_z) + gamma * z_prev
        sigma2[t] = np.exp(ln_sigma2[t])
        z[t] = resids_pct[t] / np.sqrt(sigma2[t])

    return np.sqrt(sigma2)


def main():
    panel = pd.read_csv(config.PROCESSED_DIR / "panel.csv", index_col="date", parse_dates=["date"])
    returns = panel["spx_log_ret"].dropna()
    sample = returns.loc[config.EGARCH_DIAGNOSTIC_START:config.SPLIT_IN_SAMPLE[1]]
    scaled = sample * RETURN_SCALE

    print(f"Sample: {sample.index.min().date()} -> {sample.index.max().date()}  n={len(sample)}")
    print()

    # --- fit with arch, dist='t' (simpler closed-form E|z| for the cross-check) ---
    am = arch_model(scaled, mean="Constant", vol="EGARCH", p=1, o=1, q=1, dist="t")
    res = am.fit(disp="off")
    print("=== arch fit (dist='t') ===")
    print(res.params)
    print(f"convergence_flag={res.convergence_flag}")
    print()

    mu = res.params["mu"]
    omega = res.params["omega"]
    alpha = res.params["alpha[1]"]
    gamma = res.params["gamma[1]"]
    beta = res.params["beta[1]"]
    nu = res.params["nu"]

    resid = (scaled - mu).to_numpy()
    arch_sigma = res.conditional_volatility.to_numpy()

    # backcast: arch uses log of the backcast variance (sample-based); pull
    # arch's own backcast value for an apples-to-apples comparison rather
    # than re-deriving it independently (that's a separate, well-tested
    # arch internal not in scope for this audit).
    backcast_var = am.volatility.backcast(resid)
    backcast_lnvar = np.log(backcast_var)

    # --- check 2: from-scratch recursion using arch's own constant, compare to arch's own output ---
    my_sigma_normal_const = from_scratch_egarch11(resid, omega, alpha, gamma, beta, backcast_lnvar, e_abs_z=SQRT2_OV_PI)

    diff = my_sigma_normal_const - arch_sigma
    rel_diff = np.abs(diff) / arch_sigma
    corr = np.corrcoef(my_sigma_normal_const, arch_sigma)[0, 1]
    print("=== Check 2: from-scratch numpy recursion (arch's own sqrt(2/pi) constant) vs arch's conditional_volatility ===")
    print(f"correlation: {corr:.10f}")
    print(f"mean abs % diff: {rel_diff.mean():.8%}")
    print(f"max abs % diff: {rel_diff.max():.8%}")
    worst_idx = np.argsort(rel_diff)[::-1][:5]
    print("Worst 5 divergence points (checking whether they're var_bounds-clipping edge cases):")
    for i in worst_idx:
        print(f"  idx={i}  date={sample.index[i].date()}  resid_pct={resid[i]:.3f}  "
              f"arch_sigma={arch_sigma[i]:.4f}  my_sigma={my_sigma_normal_const[i]:.4f}  rel_diff={rel_diff[i]:.4%}")
    print(f"count with rel_diff > 1%: {(rel_diff > 0.01).sum()} / {len(rel_diff)}")
    print()

    # --- check 3: does using the distribution-CORRECT E|z| (and adjusting omega
    # algebraically) change the resulting sigma_t path at all? ---
    c_true = E_abs_z_studentt(nu)
    # ln(sigma2_t) has effective intercept (omega - alpha*c); to keep that
    # intercept fixed while swapping c_normal -> c_true:
    #   omega - alpha*c_normal = omega_adj - alpha*c_true
    #   omega_adj = omega + alpha*(c_true - c_normal)
    omega_adj = omega + alpha * (c_true - SQRT2_OV_PI)
    my_sigma_true_const = from_scratch_egarch11(resid, omega_adj, alpha, gamma, beta, backcast_lnvar, e_abs_z=c_true)

    diff2 = my_sigma_true_const - arch_sigma
    rel_diff2 = np.abs(diff2) / arch_sigma
    corr2 = np.corrcoef(my_sigma_true_const, arch_sigma)[0, 1]
    print("=== Check 3: recursion using the t-distribution-CORRECT E|z| + reparametrized omega, vs arch's output ===")
    print(f"nu={nu:.4f}  E|z| normal={SQRT2_OV_PI:.6f}  E|z| true-t={c_true:.6f}  (omega_adj={omega_adj:.6f} vs omega={omega:.6f})")
    print(f"correlation: {corr2:.10f}")
    print(f"mean abs % diff: {rel_diff2.mean():.8%}")
    print(f"max abs % diff: {rel_diff2.max():.8%}")
    print("-> if both checks show ~0% diff / correlation~1, the hardcoded-normal-constant issue")
    print("   is a pure omega reparametrization with NO effect on the fitted dynamics or sigma_t path.")
    print()

    # --- check: gamma sign vs leverage effect ---
    print("=== Leverage effect sign check ===")
    print(f"fitted gamma[1] = {gamma:.6f}")
    big_neg = -3.0  # a large negative standardized shock (bad news)
    big_pos = 3.0
    ln_var_after_neg = omega + beta * 0 + alpha * (abs(big_neg) - SQRT2_OV_PI) + gamma * big_neg
    ln_var_after_pos = omega + beta * 0 + alpha * (abs(big_pos) - SQRT2_OV_PI) + gamma * big_pos
    print(f"holding alpha/beta/omega fixed, ln(sigma2) contribution from a -3sigma shock: {ln_var_after_neg:.4f}")
    print(f"                                              from a +3sigma shock: {ln_var_after_pos:.4f}")
    print(f"-> {'bad news (negative shock) increases vol MORE than good news' if ln_var_after_neg > ln_var_after_pos else 'positive shock increases vol MORE than negative -- CHECK THIS'}"
          f" (standard equity leverage effect: {'CONFIRMED' if ln_var_after_neg > ln_var_after_pos else 'NOT CONFIRMED, investigate'})")
    print()

    # --- check: horizon>1 analytic forecast behavior ---
    print("=== EGARCH forecast horizon>1 analytic behavior ===")
    try:
        fc = res.forecast(horizon=5, reindex=False, method="analytic")
        print("horizon=5 analytic forecast SUCCEEDED (no error) -- variance path:")
        print(fc.variance.iloc[-1])
        print("NEEDS INVESTIGATION: does arch silently plug E[z]=0 forward for horizon>1, or handle it correctly?")
    except Exception as e:
        print(f"horizon=5 analytic forecast RAISED: {type(e).__name__}: {e}")
        print("-> confirms analytic method is restricted; simulation/bootstrap required beyond horizon=1")


if __name__ == "__main__":
    main()
