"""Generate a full export registry with all relationships (auto + manual).

Usage:
    python -m scripts.export_registry \\
        --input  registry/manual_registry.xlsx \\
        --output registry/export_registry.xlsx
"""

from __future__ import annotations

import argparse
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from registry.loader import RegistryLoader
from registry.models import (
    DomainDef,
    EntityDef,
    PropertyDef,
    RelationshipDef,
    RegistryData,
)
from registry.writer import RegistryWriter


def _gen_auto_relationships(data: RegistryData) -> list[RelationshipDef]:
    rels: list[RelationshipDef] = []

    # IN_DOMAIN: entity → domain
    for e in data.entities:
        for dc in e.domains:
            rels.append(RelationshipDef(
                src_fqn=e.fqn, dst_fqn=dc, rel_type="IN_DOMAIN",
                is_directed=True, source="registry", status="active",
            ))

    # HAS_COLUMN: entity → property
    for p in data.properties:
        rels.append(RelationshipDef(
            src_fqn=p.entity_fqn, dst_fqn=p.fqn, rel_type="HAS_COLUMN",
            is_directed=True, source="registry", status="active",
        ))

    # REFERENCES: FK 自动建边
    for p in data.properties:
        if p.is_fk and p.ref_property_fqn:
            rels.append(RelationshipDef(
                src_fqn=p.fqn, dst_fqn=p.ref_property_fqn, rel_type="REFERENCES",
                is_directed=True, source="registry", status="active",
            ))

    return rels


def merge_relationships(
    manual: list[RelationshipDef], auto: list[RelationshipDef],
) -> list[RelationshipDef]:
    """Merge auto-generated relationships with manual ones.

    Manual relationships have higher priority: if an auto-generated
    relationship has the same (src_fqn, dst_fqn, rel_type), it is
    omitted in favor of the manual version.
    """
    manual_key = {(r.src_fqn, r.dst_fqn, r.rel_type) for r in manual}
    merged: list[RelationshipDef] = list(manual)  # keep manual first
    for r in auto:
        key = (r.src_fqn, r.dst_fqn, r.rel_type)
        if key not in manual_key:
            merged.append(r)
    return merged


def main():
    parser = argparse.ArgumentParser(description="Export full registry with all relationships")
    parser.add_argument("--input", "-i", required=True, help="Input manual registry xlsx")
    parser.add_argument("--output", "-o", required=True, help="Output export registry xlsx")
    args = parser.parse_args()

    print(f"Loading manual registry: {args.input}")
    data = RegistryLoader(args.input).load()

    print(f"  domains={len(data.domains)}  entities={len(data.entities)}  "
          f"properties={len(data.properties)}  relationships={len(data.relationships)}")

    auto_rels = _gen_auto_relationships(data)
    print(f"  auto-generated relationships: {len(auto_rels)}")

    merged = merge_relationships(data.relationships, auto_rels)
    print(f"  total after merge: {len(merged)}")

    # Build a full RegistryData with merged relationships
    export_data = RegistryData(
        domains=data.domains,
        entities=data.entities,
        properties=data.properties,
        relationships=merged,
    )

    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    RegistryWriter(path).write(export_data)
    print(f"Export written: {path}")


if __name__ == "__main__":
    main()
