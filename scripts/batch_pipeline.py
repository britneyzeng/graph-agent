"""One-click pipeline: init registry → sync to Neo4j → mine SQL → run analysis.

Usage:
    python -m scripts.batch_pipeline
    python -m scripts.batch_pipeline --xlsx registry/mock_data.xlsx --sql-dir ./stored_procs
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("batch_pipeline")


def main():
    parser = argparse.ArgumentParser(description="Batch pipeline: init → sync → mine → analyze")
    parser.add_argument("--xlsx", "-x", default="registry/mock_data.xlsx")
    parser.add_argument("--sql-dir", "-d", default=None, help="SQL files dir for mining")
    parser.add_argument("--init", action="store_true", help="Initialize blank Excel first")
    parser.add_argument("--with-mock", action="store_true", help="Write mock data (implies --init)")
    parser.add_argument("--skip-sync", action="store_true", help="Skip sync to Neo4j")
    parser.add_argument("--skip-analysis", action="store_true", help="Skip analysis")
    args = parser.parse_args()

    xlsx_path = Path(args.xlsx)

    if args.init or args.with_mock:
        logger.info("Step 0: Initializing registry ...")
        from scripts.init_registry import create_blank_workbook, write_mock_data
        xlsx_path.parent.mkdir(parents=True, exist_ok=True)
        create_blank_workbook(xlsx_path)
        if args.with_mock:
            write_mock_data(xlsx_path)
        logger.info("Registry ready at %s", xlsx_path)

    if not args.skip_sync:
        logger.info("Step 1: Sync to Neo4j ...")
        from scripts.sync_to_graph import main as sync_main
        sync_main()

    if args.sql_dir:
        logger.info("Step 2: Mining SQL ...")
        from scripts.run_mining import main as mining_main
        mining_main()

    if not args.skip_analysis:
        logger.info("Step 3: Graph analysis ...")
        from scripts.run_analysis import main as analysis_main
        analysis_main()

    logger.info("Pipeline complete.")


if __name__ == "__main__":
    main()
