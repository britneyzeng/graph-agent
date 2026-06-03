"""Run graph analysis (PageRank, Louvain) on Field and Entity graphs.

Usage:
    python -m scripts.run_analysis --algo centrality
    python -m scripts.run_analysis --algo louvain --resolution 1.5
    python -m scripts.run_analysis --algo all
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("run_analysis")


def main():
    parser = argparse.ArgumentParser(description="Run graph analysis (networkx + Kuzu)")
    parser.add_argument("--algo", choices=["centrality", "louvain", "all"], default="all")
    parser.add_argument("--resolution", type=float, default=1.0, help="Louvain resolution (>1 for finer)")
    parser.add_argument("--domain", default=None, help="Optional domain filter")
    args = parser.parse_args()

    algos = ["centrality", "louvain"] if args.algo == "all" else [args.algo]

    for algo in algos:
        logger.info("Running %s ...", algo)
        if algo == "centrality":
            from analysis.centrality import run_pagerank_field, run_pagerank_entity
            run_pagerank_field(domain=args.domain)
            run_pagerank_entity(domain=args.domain)
        elif algo == "louvain":
            from analysis.community import run_louvain_field, run_louvain_entity
            run_louvain_field(domain=args.domain, resolution=args.resolution)
            run_louvain_entity(domain=args.domain, resolution=args.resolution)

    logger.info("Analysis complete.")


if __name__ == "__main__":
    main()
