from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DomainDef:
    fqn: str
    name_cn: str
    name_en: str = ""
    parent_fqn: str | None = None
    description: str = ""
    source: str = "manual"
    status: str = "active"


@dataclass
class EntityDef:
    fqn: str
    entity_type: str
    name_cn: str = ""
    name_en: str = ""
    src_tables: list[str] = field(default_factory=list)
    domains: list[str] = field(default_factory=list)
    description: str = ""
    source: str = "manual"
    status: str = "active"


@dataclass
class PropertyDef:
    fqn: str
    entity_fqn: str
    data_type: str
    is_pk: bool = False
    ref_property_fqn: str | None = None
    description: str = ""
    name_cn: str = ""
    name_en: str = ""
    source: str = "manual"
    status: str = "active"

    @property
    def name(self) -> str:
        return self.fqn.rsplit(".", 1)[-1]


@dataclass
class LogicDef:
    fqn: str
    logic_type: str
    expression: str = ""
    name_cn: str = ""
    name_en: str = ""
    description: str = ""
    source: str = "manual"
    status: str = "active"


@dataclass
class RelationshipDef:
    src_fqn: str
    dst_fqn: str
    rel_type: str = "REFERENCES"
    is_directed: bool = True
    source: str = "introspect"
    status: str = "active"


@dataclass
class RegistryData:
    domains: list[DomainDef] = field(default_factory=list)
    entities: list[EntityDef] = field(default_factory=list)
    properties: list[PropertyDef] = field(default_factory=list)
    logics: list[LogicDef] = field(default_factory=list)
    relationships: list[RelationshipDef] = field(default_factory=list)
