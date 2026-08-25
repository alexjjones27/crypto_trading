"""Entry point: run the full Hyperliquid funding-arb backtest pipeline.

Fetches (or loads cached) funding history for BTC/ETH/SOL, runs the
maker/taker x capped/uncapped backtest matrix per asset and for the
capital-rotation variant, and writes the summary table, plots, and
markdown report to results/hyperliquid_funding_arb/.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hyperliquid_funding_arb import main

if __name__ == "__main__":
    main()
