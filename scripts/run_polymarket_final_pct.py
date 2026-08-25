"""Entry point: run the full Polymarket "final 1%" backtest pipeline.

Pulls (or loads cached) a complete census of resolved Polymarket markets,
draws a stratified random sample, runs no-lookahead crossing detection and
simulated trades under maker and taker fill assumptions, and writes the
summary tables, equity-curve plots, and markdown report to
results/polymarket_final_pct/.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from polymarket_final_pct import main

if __name__ == "__main__":
    main()
