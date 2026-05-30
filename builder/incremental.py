"""Incremental sync from registry change log to Neo4j.

Not yet implemented. Placeholder for future development.
"""

import logging

from registry.models import RegistryData

logger = logging.getLogger(__name__)


class IncrementalSync:
    def __init__(self, registry: RegistryData, change_log: list[dict]):
        self.registry = registry
        self.change_log = change_log

    def sync(self):
        logger.warning("Incremental sync not yet implemented. Performing full sync instead.")
        from builder.graph_builder import GraphBuilder
        GraphBuilder(self.registry).sync_all()
