import json
import logging
from pathlib import Path

from openpyxl import load_workbook

from registry.models import (
    ColumnDef,
    DomainDef,
    RegistryData,
    RelationshipDef,
    TableDef,
)

logger = logging.getLogger(__name__)

SHEET_DOMAIN = "Domain"
SHEET_TABLE = "Table"
SHEET_COLUMN = "Column"
SHEET_RELATIONSHIP = "Relationship"

REQUIRED_SHEETS = {SHEET_DOMAIN, SHEET_TABLE, SHEET_COLUMN, SHEET_RELATIONSHIP}


class RegistryLoader:
    def __init__(self, xlsx_path: str | Path):
        self.xlsx_path = Path(xlsx_path)

    def load(self) -> RegistryData:
        if not self.xlsx_path.exists():
            raise FileNotFoundError(f"Registry file not found: {self.xlsx_path}")

        wb = load_workbook(self.xlsx_path, read_only=True, data_only=True)
        sheet_names = set(wb.sheetnames)
        missing = REQUIRED_SHEETS - sheet_names
        if missing:
            wb.close()
            raise ValueError(f"Missing required sheets: {missing}")

        data = RegistryData(
            domains=self._load_domains(wb),
            tables=self._load_tables(wb),
            columns=self._load_columns(wb),
            relationships=self._load_relationships(wb),
        )
        wb.close()
        return data

    def _load_domains(self, wb) -> list[DomainDef]:
        ws = wb[SHEET_DOMAIN]
        rows = list(ws.iter_rows(min_row=2, values_only=True))
        result = []
        for row in rows:
            if not row or not row[0]:
                continue
            result.append(
                DomainDef(
                    code=str(row[0]).strip(),
                    name=str(row[1]).strip() if row[1] else "",
                    parent_code=str(row[2]).strip() if row[2] else None,
                    description=str(row[3]).strip() if len(row) > 3 and row[3] else "",
                    source=str(row[4]).strip() if len(row) > 4 and row[4] else "manual",
                )
            )
        return result

    def _load_tables(self, wb) -> list[TableDef]:
        ws = wb[SHEET_TABLE]
        rows = list(ws.iter_rows(min_row=2, values_only=True))
        result = []
        for row in rows:
            if not row or not row[0]:
                continue
            result.append(
                TableDef(
                    fqn=str(row[0]).strip(),
                    schema_name=str(row[1]).strip() if row[1] else "",
                    table_name=str(row[2]).strip() if row[2] else "",
                    type=str(row[3]).strip() if len(row) > 3 and row[3] else "table",
                    business_object=str(row[4]).strip() if len(row) > 4 and row[4] else "",
                    domains=self._parse_csv(row[5]) if len(row) > 5 else [],
                    comment=str(row[6]).strip() if len(row) > 6 and row[6] else "",
                    status=str(row[7]).strip() if len(row) > 7 and row[7] else "active",
                )
            )
        return result

    def _load_columns(self, wb) -> list[ColumnDef]:
        ws = wb[SHEET_COLUMN]
        rows = list(ws.iter_rows(min_row=2, values_only=True))
        result = []
        for row in rows:
            if not row or not row[0]:
                continue
            result.append(
                ColumnDef(
                    fqn=str(row[0]).strip(),
                    table_fqn=str(row[1]).strip() if row[1] else "",
                    name=str(row[2]).strip() if row[2] else "",
                    data_type=str(row[3]).strip() if row[3] else "unknown",
                    nullable=self._parse_bool(row[4]) if len(row) > 4 else True,
                    is_pk=self._parse_bool(row[5]) if len(row) > 5 else False,
                    is_fk=self._parse_bool(row[6]) if len(row) > 6 else False,
                    ref_column_fqn=str(row[7]).strip() if len(row) > 7 and row[7] else None,
                    semantic_type=str(row[8]).strip() if len(row) > 8 and row[8] else "",
                    domains=self._parse_csv(row[9]) if len(row) > 9 else [],
                    comment=str(row[10]).strip() if len(row) > 10 and row[10] else "",
                )
            )
        return result

    def _load_relationships(self, wb) -> list[RelationshipDef]:
        ws = wb[SHEET_RELATIONSHIP]
        rows = list(ws.iter_rows(min_row=2, values_only=True))
        result = []
        for row in rows:
            if not row or not row[0]:
                continue
            result.append(
                RelationshipDef(
                    src_fqn=str(row[0]).strip(),
                    dst_fqn=str(row[1]).strip() if row[1] else "",
                    node_level=str(row[2]).strip() if len(row) > 2 and row[2] else "column",
                    rel_type=str(row[3]).strip() if len(row) > 3 and row[3] else "REFERENCES",
                    is_directed=self._parse_bool(row[4]) if len(row) > 4 else True,
                    properties=self._parse_json(row[5]) if len(row) > 5 else {},
                    source=str(row[6]).strip() if len(row) > 6 and row[6] else "introspect",
                    status=str(row[7]).strip() if len(row) > 7 and row[7] else "active",
                )
            )
        return result

    @staticmethod
    def _parse_csv(value: str | None) -> list[str]:
        if not value:
            return []
        return [s.strip() for s in str(value).split(",") if s.strip()]

    @staticmethod
    def _parse_bool(value) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            return bool(value)
        s = str(value).strip().lower()
        return s in ("true", "yes", "1", "是", "y")

    @staticmethod
    def _parse_json(value: str | None) -> dict:
        if not value:
            return {}
        if isinstance(value, dict):
            return value
        try:
            return json.loads(str(value))
        except (json.JSONDecodeError, TypeError):
            logger.warning("Failed to parse JSON properties: %s", value)
            return {}
