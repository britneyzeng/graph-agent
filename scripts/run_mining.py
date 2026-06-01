"""Parse SQL files, mine relations, and write results to Kuzu graph DB.

Usage:
    python -m scripts.run_mining --sql-dir sql_samples/
    python -m scripts.run_mining --sql-dir sql_samples/ --schema registry/manual_registry.xlsx
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("run_mining")


def main():
    parser = argparse.ArgumentParser(description="Mine SQL relations and update Kuzu graph")
    parser.add_argument("--sql-dir", required=True, help="Directory containing .sql files")
    args = parser.parse_args()

    sql_dir = Path(args.sql_dir)
    if not sql_dir.is_dir():
        logger.error("SQL directory not found: %s", sql_dir)
        sys.exit(1)

    from mining.sql_parser import SqlParser
    from mining.relation_aggregator import RelationAggregator

    parser = SqlParser()
    aggregator = RelationAggregator()

    sql_files = sorted(sql_dir.glob("*.sql"))
    logger.info("Found %d SQL files in %s", len(sql_files), sql_dir)

    for sf in sql_files:
        sql = sf.read_text(encoding="utf-8")
        results = parser.parse(sql)
        for r in results:
            aggregator.add(r)
        logger.info("  Parsed %s -> %d relations", sf.name, len(results))

    from builder.schema import NT, NP, ensure_schema
    from kuzu_client import get_kuzu_client

    client = get_kuzu_client()
    ensure_schema(client)

    # Ensure rel tables for mining results
    client.execute(f"CREATE REL TABLE IF NOT EXISTS JOINS_WITH(FROM {NP} TO {NP}, frequency INT64, confidence DOUBLE)")
    client.execute(f"CREATE REL TABLE IF NOT EXISTS DERIVES_FROM(FROM {NP} TO {NP})")

    joins = aggregator.get_joins()
    logger.info("Aggregated %d JOINS_WITH relations", len(joins))
    for j in joins:
        d = j.to_dict()
        client.execute(
            f"MATCH (src:{NP} {{fqn: $src_fqn}}), (dst:{NP} {{fqn: $dst_fqn}})\n"
            f"MERGE (src)-[:JOINS_WITH {{frequency: $freq, confidence: $conf}}]->(dst)",
            {"src_fqn": d["src_fqn"], "dst_fqn": d["dst_fqn"],
             "freq": d["properties"]["frequency"], "conf": d["properties"]["confidence"]},
        )

    lineages = aggregator.get_lineage()
    logger.info("Aggregated %d DERIVES_FROM relations", len(lineages))
    for ln in lineages:
        d = ln.to_dict()
        client.execute(
            f"MATCH (src:{NP} {{fqn: $src_fqn}}), (dst:{NP} {{fqn: $dst_fqn}})\n"
            f"MERGE (src)-[:DERIVES_FROM]->(dst)",
            {"src_fqn": d["src_fqn"], "dst_fqn": d["dst_fqn"]},
        )

    logger.info("Mining complete.")


if __name__ == "__main__":
    main()
