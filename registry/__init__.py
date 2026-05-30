"""Registry package for schema metadata management.

Excel-based registry is the Single Source of Truth (SSOT).
"""

from registry.models import (
    ColumnDef,
    DomainDef,
    RegistryData,
    RelationshipDef,
    TableDef,
)
from registry.loader import RegistryLoader
from registry.writer import RegistryWriter
from registry.validator import RegistryValidator

__all__ = [
    "DomainDef",
    "TableDef",
    "ColumnDef",
    "RelationshipDef",
    "RegistryData",
    "RegistryLoader",
    "RegistryWriter",
    "RegistryValidator",
]
