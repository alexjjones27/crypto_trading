"""QQ plot of the walk-forward (expanding-window) standardized residuals,
for visual comparison against the single-fit diagnostics from step A.

Run as: python -m spx_egarch_gex.models.plot_walk_forward_diagnostics
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from scipy import stats

from spx_egarch_gex import config

def main():
    df = pd.read_csv(
        config.PROCESSED_DIR / "egarch_forecasts_expanding.csv", index_col=0, parse_dates=True
    )
    sr = df["std_resid_expanding"].dropna()

    fig, axes = plt.subplots(1, 2, figsize=(10, 5))
    stats.probplot(sr, dist="norm", plot=axes[0])
    axes[0].set_title("Walk-forward std. resid vs Normal")
    stats.probplot(sr, dist="t", sparams=(7,), plot=axes[1])
    axes[1].set_title("Walk-forward std. resid vs t(df=7)")
    fig.tight_layout()
    out = config.RESULTS_DIR / "qq_walk_forward_expanding.png"
    fig.savefig(out, dpi=110)
    plt.close(fig)
    print(f"Wrote {out}")
    print(sr.describe())


if __name__ == "__main__":
    main()
