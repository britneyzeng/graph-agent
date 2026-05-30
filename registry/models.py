from dataclasses import dataclass, field


@dataclass
class DomainDef:
    code: str
    name: str
    parent_code: str | None = None
    description: str = ""
    source: str = "manual"


@dataclass
class TableDef:
    fqn: str
    schema_name: str
    table_name: str
    type: str = "table"
    business_object: str = ""
    domains: list[str] = field(default_factory=list)
    comment: str = ""
    status: str = "active"


@dataclass
class ColumnDef:
    fqn: str
    table_fqn: str
    name: str
    data_type: str
    nullable: bool = True
    is_pk: bool = False
    is_fk: bool = False
    ref_column_fqn: str | None = None
    semantic_type: str = ""
    domains: list[str] = field(default_factory=list)
    comment: str = ""


@dataclass
class RelationshipDef:
    src_fqn: str
    dst_fqn: str
    node_level: str = "column"
    rel_type: str = "REFERENCES"
    is_directed: bool = True
    properties: dict = field(default_factory=dict)
    source: str = "introspect"
    status: str = "active"


@dataclass
class RegistryData:
    domains: list[DomainDef] = field(default_factory=list)
    tables: list[TableDef] = field(default_factory=list)
    columns: list[ColumnDef] = field(default_factory=list)
    relationships: list[RelationshipDef] = field(default_factory=list)
