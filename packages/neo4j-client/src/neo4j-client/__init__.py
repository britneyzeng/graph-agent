"""Neo4j Client Package.

This package provides client and utilities for direct interaction with
Neo4j graph database, similar to the kgraph package for Kuzu database.

Two database connections are supported:
- Schema database (neo4j-purioc, port 7683): For schema/metadata queries
- Data database (neo4j-purioc-data, port 7682): For business data queries
"""

from neo4j_client.client import (
    Neo4jClient,
    Neo4jClientError,
    close_neo4j_client,
    get_neo4j_client,
)
from neo4j_client.graph_handler import transform_paths_to_graph

__all__ = [
    "Neo4jClient",
    "Neo4jClientError",
    "close_neo4j_client",
    "get_neo4j_client",
    "transform_paths_to_graph",
]
