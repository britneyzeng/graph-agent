"""Sync registry Excel to Kuzu graph database.

Usage:
    python -m scripts.sync_to_graph --xlsx registry/manual_registry.xlsx
    python -m scripts.sync_to_graph --xlsx registry/manual_registry.xlsx --validate-only
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("sync_to_graph")


def main():
    parser = argparse.ArgumentParser(description="Sync registry Excel to Kuzu graph")
    parser.add_argument("--xlsx", "-x", default="registry/manual_registry.xlsx", help="Registry Excel path")
    parser.add_argument("--validate-only", action="store_true", help="Only validate, skip graph sync")
    args = parser.parse_args()

    xlsx_path = Path(args.xlsx)
    if not xlsx_path.exists():
        logger.error("Registry file not found: %s", xlsx_path)
        sys.exit(1)

    from registry.loader import RegistryLoader
    from registry.validator import RegistryValidator

    logger.info("Loading registry from %s ...", xlsx_path)
    data = RegistryLoader(xlsx_path).load()
    logger.info("Loaded %d domains, %d entities, %d properties, %d relationships",
                len(data.domains), len(data.entities), len(data.properties), len(data.relationships))

    validator = RegistryValidator(data)
    errors = validator.validate()
    if errors:
        logger.error("Validation FAILED with %d errors:", len(errors))
        for e in errors:
            logger.error("  %s", e)
        sys.exit(1)
    logger.info("Validation passed.")

    if args.validate_only:
        return

    from builder.graph_builder import GraphBuilder
    builder = GraphBuilder(data)
    asyncio.run(builder.sync_all())
    logger.info("Done.")


if __name__ == "__main__":
    main()
