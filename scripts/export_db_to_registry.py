"""Export Kuzu graph DB back to registry Excel file.

Reads all nodes and relationships from the Kuzu database and writes
them to a registry Excel file that can be used with sync_to_graph.

Usage:
    python -m scripts.export_db_to_registry --output registry/exported_registry.xlsx
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from kuzu_client import get_kuzu_client, close_kuzu_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("export_db_to_registry")


def _pop(row: dict, key: str, default: str = "") -> str:
    val = row.get(key, default)
    return val if val is not None else default


def main():
    parser = argparse.ArgumentParser(description="Export Kuzu graph to registry Excel")
    parser.add_argument("--output", "-o", default="registry/exported_registry.xlsx", help="Output xlsx path")
    args = parser.parse_args()

    client = get_kuzu_client()

    domains = client.execute("MATCH (d:Domain) RETURN d.* ORDER BY d.code")
    logger.info("Read %d Domain nodes", len(domains))

    entities = client.execute(
        "MATCH (n:Entity) WHERE n.entity_type IS NOT NULL RETURN n.* ORDER BY n.fqn"
    )
    logger.info("Read %d Entity nodes", len(entities))

    fields = client.execute("MATCH (c:Field) RETURN c.* ORDER BY c.fqn")
    logger.info("Read %d Field nodes", len(fields))

    rows_domain = []
    for d in domains:
        row = {k.replace("d.", ""): v for k, v in d.items()}
        rows_domain.append({
            "code": _pop(row, "code"),
            "name_cn": _pop(row, "name_cn"),
            "name_en": _pop(row, "name_en"),
            "parent_code": _pop(row, "parent_code"),
            "description": _pop(row, "description"),
            "source": _pop(row, "source"),
            "status": _pop(row, "status", "active"),
        })

    rows_entity = []
    for e in entities:
        row = {k.replace("n.", ""): v for k, v in e.items()}
        rows_entity.append({
            "fqn": _pop(row, "fqn"),
            "entity_type": _pop(row, "entity_type"),
            "name_cn": _pop(row, "name_cn"),
            "name_en": _pop(row, "name_en"),
            "src_tables": row.get("src_tables") or [],
            "domains": row.get("domains") or [],
            "description": _pop(row, "description"),
            "source": _pop(row, "source"),
            "status": _pop(row, "status", "active"),
        })

    rows_property = []
    for p in fields:
        row = {k.replace("c.", ""): v for k, v in p.items()}
        rows_property.append({
            "fqn": _pop(row, "fqn"),
            "entity_fqn": _pop(row, "entity_fqn"),
            "data_type": _pop(row, "data_type"),
            "is_pk": row.get("is_pk", False),
            "is_fk": row.get("is_fk", False),
            "ref_property_fqn": _pop(row, "ref_property_fqn"),
            "description": _pop(row, "description"),
            "name_cn": _pop(row, "name_cn"),
            "name_en": _pop(row, "name_en"),
            "source": _pop(row, "source"),
            "status": _pop(row, "status", "active"),
        })

    rel_types = [
        r["name"] for r in client.execute("CALL SHOW_TABLES() RETURN *")
        if r["type"] == "REL" and r["name"] != "HAS_PROPERTY"
    ]
    rel_rows = []
    for rel_type in rel_types:
        try:
            rels = client.execute(
                f"MATCH (src)-[r:{rel_type}]->(dst) RETURN src.fqn AS src_fqn, dst.fqn AS dst_fqn, r.*"
            )
            for r in rels:
                rel_rows.append({
                    "src_fqn": _pop(r, "src_fqn"),
                    "dst_fqn": _pop(r, "dst_fqn"),
                    "rel_type": rel_type,
                    "is_directed": True,
                    "source": _pop(r, "source"),
                    "status": _pop(r, "status", "active"),
                })
        except Exception as e:
            logger.warning("Skipping rel %s: %s", rel_type, e)

    logger.info("Read %d relationships", len(rel_rows))

    from registry.models import DomainDef, EntityDef, PropertyDef, RelationshipDef, RegistryData
    from registry.writer import RegistryWriter

    data = RegistryData(
        domains=[DomainDef(**d) for d in rows_domain],
        entities=[EntityDef(**e) for e in rows_entity],
        properties=[PropertyDef(**p) for p in rows_property],
        relationships=[RelationshipDef(**r) for r in rel_rows],
    )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    RegistryWriter(output_path).write(data)
    logger.info("Exported %d domains, %d entities, %d properties, %d relationships -> %s",
                len(data.domains), len(data.entities), len(data.properties), len(data.relationships), output_path)

    close_kuzu_client()


if __name__ == "__main__":
    main()
