"""End-to-end GraphBuilder sync test (requires A20_NEO4J_MOCK=1).

Builds mock RegistryData in-memory, runs full sync_all, and verifies
node creation + entity enrichment via mock client internal state.

NOTE: The mock client does not support every Cypher pattern
(``CALL apoc.merge.node``, complex ``MERGE …-[]→…`` with ``UNWIND``),
so only node creation and enrichment are verifiable.
"""

from __future__ import annotations

import asyncio
from collections import Counter

from registry.models import (
    DomainDef,
    EntityDef,
    PropertyDef,
    RegistryData,
    RelationshipDef,
)
from registry.validator import RegistryValidator
from builder.graph_builder import GraphBuilder


def _build_mock_data() -> RegistryData:
    """Small but representative procurement domain dataset."""
    return RegistryData(
        domains=[
            DomainDef(code="procurement", name_cn="采购域"),
            DomainDef(code="supply_base", name_cn="供应商管理", parent_code="procurement"),
            DomainDef(code="po_management", name_cn="采购订单管理", parent_code="procurement"),
            DomainDef(code="finance", name_cn="财务域"),
        ],
        entities=[
            EntityDef(
                fqn="proc.public.supplier", entity_type="Supplier",
                src_tables=["proc.public.supplier"], domains=["supply_base"],
                name_cn="供应商主数据",
            ),
            EntityDef(
                fqn="proc.public.po_line", entity_type="PurchaseOrderLine",
                src_tables=["proc.public.po_line"], domains=["po_management"],
                name_cn="采购订单行",
            ),
            EntityDef(
                fqn="proc.public.po_order", entity_type="PurchaseOrder",
                src_tables=["proc.public.po_order"], domains=["po_management"],
                name_cn="采购订单",
            ),
        ],
        properties=[
            PropertyDef(fqn="proc.public.supplier.id", entity_fqn="proc.public.supplier",
                        data_type="bigint", is_pk=True, name_cn="主键"),
            PropertyDef(fqn="proc.public.supplier.code", entity_fqn="proc.public.supplier",
                        data_type="varchar(32)", name_cn="供应商编码"),
            PropertyDef(fqn="proc.public.supplier.name", entity_fqn="proc.public.supplier",
                        data_type="varchar(200)", name_cn="供应商名称"),
            PropertyDef(fqn="proc.public.supplier.status", entity_fqn="proc.public.supplier",
                        data_type="varchar(16)", name_cn="供应商状态"),
            PropertyDef(fqn="proc.public.supplier.created_at", entity_fqn="proc.public.supplier",
                        data_type="timestamp", name_cn="创建时间"),
            PropertyDef(fqn="proc.public.po_line.id", entity_fqn="proc.public.po_line",
                        data_type="bigint", is_pk=True, name_cn="主键"),
            PropertyDef(fqn="proc.public.po_line.po_order_id", entity_fqn="proc.public.po_line",
                        data_type="bigint", is_fk=True, ref_property_fqn="proc.public.po_order.id",
                        name_cn="所属采购订单ID"),
            PropertyDef(fqn="proc.public.po_line.line_no", entity_fqn="proc.public.po_line",
                        data_type="int", name_cn="行号"),
            PropertyDef(fqn="proc.public.po_order.id", entity_fqn="proc.public.po_order",
                        data_type="bigint", is_pk=True, name_cn="主键"),
            PropertyDef(fqn="proc.public.po_order.order_no", entity_fqn="proc.public.po_order",
                        data_type="varchar(32)", name_cn="采购订单编号"),
        ],
        relationships=[],
    )


async def test_sync_all():
    data = _build_mock_data()
    assert len(data.domains) == 4
    assert len(data.entities) == 3
    assert len(data.properties) == 10
    assert len(data.relationships) == 0

    errors = RegistryValidator(data).validate()
    assert not errors, errors

    builder = GraphBuilder(data)
    await builder.sync_all()

    c = builder._client()

    # ── 1. Node counts (mock handles these) ───────────────────────────

    async def _count(q: str) -> int:
        rows = await c.execute_schema(q, {})
        return rows[0]["c"] if rows else 0

    assert await _count("MATCH (n:Domain) RETURN count(*) AS c") == 4
    assert await _count("MATCH (n:Property) RETURN count(*) AS c") == 10

    entity_count = await _count(
        "MATCH (n) WHERE n.entity_type IS NOT NULL RETURN count(*) AS c"
    )
    assert entity_count == 3, f"Expected 3 entities, got {entity_count}"

    # ── 2. Relationship counts (via mock internal state) ──────────────

    rel_types = Counter(r.type_ for r in c._rels)
    print(f"Relationship breakdown: {dict(rel_types)}")

    # Property IN_DOMAIN no longer created (domains removed from PropertyDef).
    # Entity IN_DOMAIN not created by mock (apoc.merge.node limitation).
    assert len(c._rels) == 0

    # ── 3. Entity enrichment (check in-memory node props) ──

    supplier = c._nodes.get("proc.public.supplier")
    assert supplier is not None
    sp = supplier.props
    print(f"Supplier: entity_type={sp.get('entity_type')} "
          f"pcount={sp.get('property_count')} "
          f"has_pk={sp.get('has_pk')} has_fk={sp.get('has_fk')}")
    assert sp.get("entity_type") == "Supplier"
    assert sp.get("property_count") == 5
    assert sp.get("has_pk") is True
    assert sp.get("has_fk") is False
    assert "id" in sp.get("pk_properties", [])
    # All 5 properties appear in properties summary (no exclusion)
    assert len(sp.get("properties", {})) == 5

    po_line = c._nodes.get("proc.public.po_line")
    assert po_line is not None
    lp = po_line.props
    print(f"PO_Line: pk={lp.get('pk_properties')} fk={lp.get('fk_properties')} "
          f"has_pk={lp.get('has_pk')} has_fk={lp.get('has_fk')}")
    assert lp.get("has_fk") is True
    assert "po_order_id" in lp.get("fk_properties", [])
    assert lp.get("has_pk") is True

    # ── 4. Domain nodes stored with code as key ──

    for code in ("procurement", "supply_base", "po_management", "finance"):
        domain = c._nodes.get(code)
        assert domain is not None, f"Domain {code} not found"
        assert domain.props.get("code") == code

    print("\nAll mock-supported assertions passed.")


if __name__ == "__main__":
    asyncio.run(test_sync_all())
