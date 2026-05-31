from __future__ import annotations

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
        self._check_entity_fqn_unique()
        self._check_property_fqn_unique()
        self._check_property_entity_ref()
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

    def _check_entity_fqn_unique(self):
        seen = {}
        for i, e in enumerate(self.data.entities):
            if not e.entity_type:
                self.errors.append(
                    ValidationError("Entity", i + 2, f"entity_type is empty for fqn '{e.fqn}'")
                )
            if e.fqn in seen:
                self.errors.append(
                    ValidationError("Entity", i + 2, f"duplicate fqn '{e.fqn}' (also at row {seen[e.fqn]})")
                )
            seen[e.fqn] = i + 2

    def _check_property_fqn_unique(self):
        seen = {}
        for i, p in enumerate(self.data.properties):
            if p.fqn in seen:
                self.errors.append(
                    ValidationError("Property", i + 2, f"duplicate fqn '{p.fqn}' (also at row {seen[p.fqn]})")
                )
            seen[p.fqn] = i + 2

    def _check_property_entity_ref(self):
        entity_fqns = {e.fqn for e in self.data.entities}
        for i, p in enumerate(self.data.properties):
            if p.entity_fqn not in entity_fqns:
                self.errors.append(
                    ValidationError("Property", i + 2, f"entity_fqn '{p.entity_fqn}' not found in Entity sheet")
                )

    def _check_fk_ref(self):
        prop_fqns = {p.fqn for p in self.data.properties}
        for i, p in enumerate(self.data.properties):
            if p.is_fk and p.ref_property_fqn:
                if p.ref_property_fqn not in prop_fqns:
                    self.errors.append(
                        ValidationError("Property", i + 2, f"FK ref_property_fqn '{p.ref_property_fqn}' not found")
                    )

    def _check_relationship_ref(self):
        all_fqns = {p.fqn for p in self.data.properties}
        all_fqns |= {e.fqn for e in self.data.entities}
        all_fqns |= {d.code for d in self.data.domains}
        for i, r in enumerate(self.data.relationships):
            if r.src_fqn not in all_fqns:
                self.errors.append(
                    ValidationError("Relationship", i + 2,
                                   f"src_fqn '{r.src_fqn}' not found in any sheet (Entity/Property/Domain)")
                )
            if r.dst_fqn not in all_fqns:
                self.errors.append(
                    ValidationError("Relationship", i + 2,
                                   f"dst_fqn '{r.dst_fqn}' not found in any sheet (Entity/Property/Domain)")
                )

    def _check_domain_refs(self):
        domain_codes = {d.code for d in self.data.domains}
        for i, e in enumerate(self.data.entities):
            for dc in e.domains:
                if dc not in domain_codes:
                    self.errors.append(
                        ValidationError("Entity", i + 2, f"domain '{dc}' not found in Domain sheet")
                    )
