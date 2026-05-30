import json
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from registry.models import (
    ColumnDef,
    DomainDef,
    RegistryData,
    RelationshipDef,
    TableDef,
)

HEADER_FILL = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
HEADER_FONT = Font(color="FFFFFF", bold=True)


class RegistryWriter:
    def __init__(self, xlsx_path: str | Path):
        self.xlsx_path = Path(xlsx_path)

    def write(self, data: RegistryData) -> Path:
        wb = Workbook()

        self._write_domains(wb, data.domains)
        self._write_tables(wb, data.tables)
        self._write_columns(wb, data.columns)
        self._write_relationships(wb, data.relationships)

        wb.save(self.xlsx_path)
        return self.xlsx_path

    def _write_header(self, ws, headers: list[str]):
        for col_idx, header in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col_idx, value=header)
            cell.fill = HEADER_FILL
            cell.font = HEADER_FONT
        ws.freeze_panes = "A2"

    @staticmethod
    def _to_csv(values: list[str]) -> str:
        return ",".join(values)

    @staticmethod
    def _to_bool(val: bool) -> str:
        return "true" if val else "false"

    @staticmethod
    def _to_json(val: dict) -> str:
        return json.dumps(val, ensure_ascii=False) if val else ""

    def _write_domains(self, wb: Workbook, domains: list[DomainDef]):
        ws = wb.active
        ws.title = "Domain"
        self._write_header(ws, ["code", "name", "parent_code", "description", "source"])
        for d in domains:
            ws.append(
                [d.code, d.name, d.parent_code or "", d.description, d.source]
            )

    def _write_tables(self, wb: Workbook, tables: list[TableDef]):
        ws = wb.create_sheet("Table")
        self._write_header(
            ws, ["fqn", "schema_name", "table_name", "type", "business_object", "domains", "comment", "status"]
        )
        for t in tables:
            ws.append(
                [
                    t.fqn,
                    t.schema_name,
                    t.table_name,
                    t.type,
                    t.business_object,
                    self._to_csv(t.domains),
                    t.comment,
                    t.status,
                ]
            )

    def _write_columns(self, wb: Workbook, columns: list[ColumnDef]):
        ws = wb.create_sheet("Column")
        self._write_header(
            ws,
            [
                "fqn",
                "table_fqn",
                "name",
                "data_type",
                "nullable",
                "is_pk",
                "is_fk",
                "ref_column_fqn",
                "semantic_type",
                "domains",
                "comment",
            ],
        )
        for c in columns:
            ws.append(
                [
                    c.fqn,
                    c.table_fqn,
                    c.name,
                    c.data_type,
                    self._to_bool(c.nullable),
                    self._to_bool(c.is_pk),
                    self._to_bool(c.is_fk),
                    c.ref_column_fqn or "",
                    c.semantic_type,
                    self._to_csv(c.domains),
                    c.comment,
                ]
            )

    def _write_relationships(self, wb: Workbook, relationships: list[RelationshipDef]):
        ws = wb.create_sheet("Relationship")
        self._write_header(
            ws,
            [
                "src_fqn",
                "dst_fqn",
                "node_level",
                "rel_type",
                "is_directed",
                "properties",
                "source",
                "status",
            ],
        )
        for r in relationships:
            ws.append(
                [
                    r.src_fqn,
                    r.dst_fqn,
                    r.node_level,
                    r.rel_type,
                    self._to_bool(r.is_directed),
                    self._to_json(r.properties),
                    r.source,
                    r.status,
                ]
            )

    def append_relationships(self, relationships: list[RelationshipDef]) -> Path:
        from openpyxl import load_workbook

        wb = load_workbook(self.xlsx_path)
        ws = wb["Relationship"]
        for r in relationships:
            ws.append(
                [
                    r.src_fqn,
                    r.dst_fqn,
                    r.node_level,
                    r.rel_type,
                    self._to_bool(r.is_directed),
                    self._to_json(r.properties),
                    r.source,
                    r.status,
                ]
            )
        wb.save(self.xlsx_path)
        return self.xlsx_path
