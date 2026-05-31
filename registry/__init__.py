"""Registry package for schema metadata management.

Excel-based registry is the Single Source of Truth (SSOT).
"""

from registry.models import (
    DomainDef,
    EntityDef,
    PropertyDef,
    RegistryData,
    RelationshipDef,
)
from registry.loader import RegistryLoader
from registry.writer import RegistryWriter
from registry.validator import RegistryValidator

__all__ = [
    "DomainDef",
    "EntityDef",
    "PropertyDef",
    "RelationshipDef",
    "RegistryData",
    "RegistryLoader",
    "RegistryWriter",
    "RegistryValidator",
]
