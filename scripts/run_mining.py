"""Run SQL relationship mining pipeline.

Usage:
    python -m scripts.run_mining --sql-dir ./stored_procs --xlsx registry/mock_data.xlsx
    python -m scripts.run_mining --sql-dir ./stored_procs --xlsx registry/mock_data.xlsx --workers 8
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("run_mining")


def main():
    parser = argparse.ArgumentParser(description="Run SQL relationship mining")
    parser.add_argument("--sql-dir", "-d", required=True, help="Directory containing .sql stored procedure files")
    parser.add_argument("--xlsx", "-x", default="registry/mock_data.xlsx", help="Registry Excel path")
    parser.add_argument("--workers", "-w", type=int, default=4, help="Parallel worker count")
    parser.add_argument("--use-llm", action="store_true", help="Enable LLM semantic judgment")
    args = parser.parse_args()

    sql_dir = Path(args.sql_dir)
    if not sql_dir.is_dir():
        logger.error("SQL directory not found: %s", sql_dir)
        sys.exit(1)

    logger.info("Scanning %s for .sql files ...", sql_dir)
    sql_files = list(sql_dir.rglob("*.sql"))
    logger.info("Found %d SQL files", len(sql_files))

    logger.warning("Mining pipeline not yet fully implemented. Placeholder for sqlglot AST parsing.")

    from registry.loader import RegistryLoader

    data = RegistryLoader(args.xlsx).load()
    logger.info("Loaded registry: %d tables, %d columns", len(data.tables), len(data.columns))

    logger.info(
        "Pipeline stages:\n"
        "  1. Multi-process sqlglot parse %d files\n"
        "  2. Extract JOIN / DERIVES_FROM / CO_USED_WITH\n"
        "  3. Cross-file aggregate (frequency, PMI)\n"
        "  4. %s LLM semantic judgment\n"
        "  5. Write back to Relationship sheet",
        len(sql_files), "With" if args.use_llm else "Without",
    )


if __name__ == "__main__":
    main()
