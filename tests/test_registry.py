"""Tests for registry module - loader, validator, writer."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from registry.loader import RegistryLoader
from registry.models import (
    ColumnDef,
    DomainDef,
    RegistryData,
    RelationshipDef,
    TableDef,
)
from registry.validator import RegistryValidator
from registry.writer import RegistryWriter


@pytest.fixture
def mock_data() -> RegistryData:
    return RegistryData(
        domains=[
            DomainDef(code="procurement", name="采购域", source="manual"),
            DomainDef(code="finance", name="财务域", source="manual"),
        ],
        tables=[
            TableDef(fqn="db.public.po_order", schema_name="public", table_name="po_order", domains=["procurement"]),
            TableDef(fqn="db.public.supplier", schema_name="public", table_name="supplier", domains=["procurement"]),
        ],
        columns=[
            ColumnDef(
                fqn="db.public.po_order.id",
                table_fqn="db.public.po_order",
                name="id",
                data_type="bigint",
                nullable=False,
                is_pk=True,
            ),
            ColumnDef(
                fqn="db.public.po_order.supplier_id",
                table_fqn="db.public.po_order",
                name="supplier_id",
                data_type="bigint",
                is_fk=True,
                ref_column_fqn="db.public.supplier.id",
                domains=["procurement"],
            ),
            ColumnDef(
                fqn="db.public.supplier.id",
                table_fqn="db.public.supplier",
                name="id",
                data_type="bigint",
                nullable=False,
                is_pk=True,
            ),
        ],
        relationships=[
            RelationshipDef(
                src_fqn="db.public.po_order.supplier_id",
                dst_fqn="db.public.supplier.id",
                rel_type="REFERENCES",
                is_directed=True,
                source="introspect",
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
            assert len(loaded.tables) == 2
            assert len(loaded.columns) == 3
            assert len(loaded.relationships) == 1

    def test_append_relationships(self, mock_data):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "registry.xlsx"
            RegistryWriter(path).write(mock_data)

            new_rel = RelationshipDef(
                src_fqn="db.public.po_order.id",
                dst_fqn="db.public.supplier.id",
                rel_type="JOINS_WITH",
                properties={"frequency": 5},
                source="inferred:sqlglot",
            )
            RegistryWriter(path).append_relationships([new_rel])

            loaded = RegistryLoader(path).load()
            assert len(loaded.relationships) == 2


class TestRegistryValidator:
    def test_valid_data_passes(self, mock_data):
        errors = RegistryValidator(mock_data).validate()
        assert len(errors) == 0

    def test_duplicate_table_fqn(self, mock_data):
        mock_data.tables.append(
            TableDef(fqn="db.public.po_order", schema_name="public", table_name="po_order_dup")
        )
        errors = RegistryValidator(mock_data).validate()
        assert any("duplicate" in e.message for e in errors)

    def test_orphan_fk(self, mock_data):
        mock_data.columns.append(
            ColumnDef(
                fqn="db.public.po_order.bad_fk",
                table_fqn="db.public.po_order",
                name="bad_fk",
                data_type="bigint",
                is_fk=True,
                ref_column_fqn="db.public.nonexistent.id",
            )
        )
        errors = RegistryValidator(mock_data).validate()
        assert any("FK ref_column_fqn" in e.message for e in errors)

    def test_nonexistent_domain(self, mock_data):
        mock_data.tables.append(
            TableDef(fqn="db.public.other", schema_name="public", table_name="other", domains=["nonexistent"])
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

    def test_parse_csv(self):
        from registry.loader import RegistryLoader

        loader = RegistryLoader("dummy")
        assert loader._parse_csv("a,b,c") == ["a", "b", "c"]
        assert loader._parse_csv("") == []
        assert loader._parse_csv(None) == []

    def test_parse_json(self):
        from registry.loader import RegistryLoader

        loader = RegistryLoader("dummy")
        assert loader._parse_json('{"freq": 5}') == {"freq": 5}
        assert loader._parse_json("") == {}
        assert loader._parse_json(None) == {}
