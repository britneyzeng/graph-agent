from registry.models import RegistryData


class ValidationError:
    def __init__(self, sheet: str, row: int, message: str):
        self.sheet = sheet
        self.row = row
        self.message = message

    def __repr__(self):
        return f"[{self.sheet}:{self.row}] {self.message}"


class RegistryValidator:
    def __init__(self, data: RegistryData):
        self.data = data
        self.errors: list[ValidationError] = []

    def validate(self) -> list[ValidationError]:
        self.errors.clear()
        self._check_domain_codes()
        self._check_table_fqn_unique()
        self._check_column_fqn_unique()
        self._check_column_table_ref()
        self._check_fk_ref()
        self._check_relationship_ref()
        self._check_domain_refs()
        return self.errors

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    def _check_domain_codes(self):
        codes = {d.code for d in self.data.domains}
        for i, d in enumerate(self.data.domains):
            if d.parent_code and d.parent_code not in codes:
                self.errors.append(
                    ValidationError("Domain", i + 2, f"parent_code '{d.parent_code}' not found")
                )

    def _check_table_fqn_unique(self):
        seen = {}
        for i, t in enumerate(self.data.tables):
            if t.fqn in seen:
                self.errors.append(
                    ValidationError("Table", i + 2, f"duplicate fqn '{t.fqn}' (also at row {seen[t.fqn]})")
                )
            seen[t.fqn] = i + 2

    def _check_column_fqn_unique(self):
        seen = {}
        for i, c in enumerate(self.data.columns):
            if c.fqn in seen:
                self.errors.append(
                    ValidationError("Column", i + 2, f"duplicate fqn '{c.fqn}' (also at row {seen[c.fqn]})")
                )
            seen[c.fqn] = i + 2

    def _check_column_table_ref(self):
        table_fqns = {t.fqn for t in self.data.tables}
        for i, c in enumerate(self.data.columns):
            if c.table_fqn not in table_fqns:
                self.errors.append(
                    ValidationError("Column", i + 2, f"table_fqn '{c.table_fqn}' not found in Table sheet")
                )

    def _check_fk_ref(self):
        col_fqns = {c.fqn for c in self.data.columns}
        for i, c in enumerate(self.data.columns):
            if c.is_fk and c.ref_column_fqn:
                if c.ref_column_fqn not in col_fqns:
                    self.errors.append(
                        ValidationError("Column", i + 2, f"FK ref_column_fqn '{c.ref_column_fqn}' not found")
                    )

    def _check_relationship_ref(self):
        col_fqns = {c.fqn for c in self.data.columns}
        table_fqns = {t.fqn for t in self.data.tables}
        for i, r in enumerate(self.data.relationships):
            if r.node_level == "column":
                if r.src_fqn not in col_fqns:
                    self.errors.append(
                        ValidationError("Relationship", i + 2, f"src_fqn '{r.src_fqn}' not found in Column sheet")
                    )
                if r.dst_fqn not in col_fqns:
                    self.errors.append(
                        ValidationError("Relationship", i + 2, f"dst_fqn '{r.dst_fqn}' not found in Column sheet")
                    )
            else:
                if r.src_fqn not in table_fqns:
                    self.errors.append(
                        ValidationError("Relationship", i + 2, f"src_fqn '{r.src_fqn}' not found in Table sheet")
                    )
                if r.dst_fqn not in table_fqns:
                    self.errors.append(
                        ValidationError("Relationship", i + 2, f"dst_fqn '{r.dst_fqn}' not found in Table sheet")
                    )

    def _check_domain_refs(self):
        domain_codes = {d.code for d in self.data.domains}
        for i, t in enumerate(self.data.tables):
            for dc in t.domains:
                if dc not in domain_codes:
                    self.errors.append(
                        ValidationError("Table", i + 2, f"domain '{dc}' not found in Domain sheet")
                    )
        for i, c in enumerate(self.data.columns):
            for dc in c.domains:
                if dc not in domain_codes:
                    self.errors.append(
                        ValidationError("Column", i + 2, f"domain '{dc}' not found in Domain sheet")
                    )
