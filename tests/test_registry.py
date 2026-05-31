"""Tests for registry module - loader, validator, writer."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from registry.loader import RegistryLoader
from registry.models import (
    DomainDef,
    EntityDef,
    PropertyDef,
    RegistryData,
    RelationshipDef,
)
from registry.validator import RegistryValidator
from registry.writer import RegistryWriter


@pytest.fixture
def mock_data() -> RegistryData:
    return RegistryData(
        domains=[
            DomainDef(code="procurement", name_cn="采购域", name_en="Procurement", source="manual", status="active"),
            DomainDef(code="finance", name_cn="财务域", name_en="Finance", source="manual", status="active"),
        ],
        entities=[
            EntityDef(fqn="db.public.po_order", entity_type="PurchaseOrder", name_cn="采购订单", name_en="PO Order",
                      src_tables=["db.public.po_order"], domains=["procurement"], description="订单头表", source="manual"),
            EntityDef(fqn="db.public.supplier", entity_type="Supplier", name_cn="供应商", name_en="Supplier",
                      src_tables=["db.public.supplier"], domains=["procurement"], source="manual"),
        ],
        properties=[
            PropertyDef(
                fqn="db.public.po_order.id",
                entity_fqn="db.public.po_order",
                data_type="bigint",
                is_pk=True,
                name_cn="主键",
                source="manual",
                status="active",
            ),
            PropertyDef(
                fqn="db.public.po_order.supplier_id",
                entity_fqn="db.public.po_order",
                data_type="bigint",
                is_fk=True,
                ref_property_fqn="db.public.supplier.id",
                name_cn="供应商ID",
                source="manual",
                status="active",
            ),
            PropertyDef(
                fqn="db.public.supplier.id",
                entity_fqn="db.public.supplier",
                data_type="bigint",
                is_pk=True,
                name_cn="主键",
                source="manual",
                status="active",
            ),
        ],
        relationships=[
            RelationshipDef(
                src_fqn="procurement",
                dst_fqn="db.public.supplier",
                rel_type="IN_DOMAIN",
                source="manual",
                status="active",
            ),
            RelationshipDef(
                src_fqn="procurement",
                dst_fqn="db.public.po_order",
                rel_type="IN_DOMAIN",
                source="manual",
                status="active",
            ),
        ],
    )


class TestRegistryWriter:
    def test_write_and_read_roundtrip(self, mock_data):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "registry.xlsx"
            RegistryWriter(path).write(mock_data)

            loaded = RegistryLoader(path).load()
            assert len(loaded.domains) == 2
            assert len(loaded.entities) == 2
            assert len(loaded.properties) == 3
            assert len(loaded.relationships) == 2

    def test_append_relationships(self, mock_data):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "registry.xlsx"
            RegistryWriter(path).write(mock_data)

            new_rel = RelationshipDef(
                src_fqn="db.public.po_order",
                dst_fqn="db.public.supplier",
                rel_type="HAS_LINE",
                source="inferred:sqlglot",
            )
            RegistryWriter(path).append_relationships([new_rel])

            loaded = RegistryLoader(path).load()
            assert len(loaded.relationships) == 3


class TestRegistryValidator:
    def test_valid_data_passes(self, mock_data):
        errors = RegistryValidator(mock_data).validate()
        assert len(errors) == 0

    def test_duplicate_entity_fqn(self, mock_data):
        mock_data.entities.append(
            EntityDef(fqn="db.public.po_order", entity_type="PurchaseOrder", src_tables=["po_order_dup"])
        )
        errors = RegistryValidator(mock_data).validate()
        assert any("duplicate" in e.message for e in errors)

    def test_orphan_fk(self, mock_data):
        mock_data.properties.append(
            PropertyDef(
                fqn="db.public.po_order.bad_fk",
                entity_fqn="db.public.po_order",
                data_type="bigint",
                is_fk=True,
                ref_property_fqn="db.public.nonexistent.id",
            )
        )
        errors = RegistryValidator(mock_data).validate()
        assert any("FK ref" in e.message for e in errors)

    def test_nonexistent_domain(self, mock_data):
        mock_data.entities.append(
            EntityDef(fqn="db.public.other", entity_type="Other", src_tables=["other"], domains=["nonexistent"])
        )
        errors = RegistryValidator(mock_data).validate()
        assert any("domain" in e.message for e in errors)

    def test_nonexistent_relationship_ref(self, mock_data):
        mock_data.relationships.append(
            RelationshipDef(
                src_fqn="db.public.nonexistent.col",
                dst_fqn="db.public.supplier.id",
                rel_type="REFERENCES",
            )
        )
        errors = RegistryValidator(mock_data).validate()
        assert any("src_fqn" in e.message for e in errors)


class TestRegistryLoader:
    def test_missing_file(self):
        with pytest.raises(FileNotFoundError):
            RegistryLoader("nonexistent.xlsx").load()

    def test_parse_bool_variants(self):
        from registry.loader import RegistryLoader

        loader = RegistryLoader("dummy")
        assert loader._parse_bool(True) is True
        assert loader._parse_bool(False) is False
        assert loader._parse_bool(1) is True
        assert loader._parse_bool(0) is False
        assert loader._parse_bool("true") is True
        assert loader._parse_bool("false") is False
        assert loader._parse_bool("yes") is True
        assert loader._parse_bool("是") is True

    def test_parse_json(self):
        from registry.loader import RegistryLoader

        loader = RegistryLoader("dummy")
        assert loader._parse_json('{"freq": 5}') == {"freq": 5}
        assert loader._parse_json("") == {}
        assert loader._parse_json(None) == {}
