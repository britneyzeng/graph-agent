"""Run graph analysis (PageRank, Louvain, similarity) and write results to Kuzu.

Usage:
    python -m scripts.run_analysis --algo centrality --xlsx registry/manual_registry.xlsx
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
    parser.add_argument("--algo", choices=["centrality", "louvain", "similarity", "all"], default="all")
    parser.add_argument("--xlsx", "-x", default="registry/manual_registry.xlsx")
    parser.add_argument("--resolution", type=float, default=1.0, help="Louvain resolution (>1 for finer)")
    parser.add_argument("--top-k", type=int, default=10, help="Top K for similarity")
    parser.add_argument("--domain", default=None, help="Optional domain filter")
    args = parser.parse_args()

    algos = ["centrality", "louvain", "similarity"] if args.algo == "all" else [args.algo]

    for algo in algos:
        logger.info("Running %s ...", algo)
        if algo == "centrality":
            from analysis.centrality import run_pagerank, run_betweenness
            run_pagerank(domain=args.domain)
            run_betweenness(domain=args.domain)
        elif algo == "louvain":
            from analysis.community import run_louvain
            run_louvain(domain=args.domain, resolution=args.resolution)
        elif algo == "similarity":
            from analysis.similarity import run_node_similarity
            run_node_similarity(domain=args.domain, top_k=args.top_k)

    logger.info("Analysis complete.")


if __name__ == "__main__":
    main()
