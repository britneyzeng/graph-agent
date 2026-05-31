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

try:
    from neo4j_client.mock_client import MockNeo4jClient, get_mock_client, close_mock_client
except ImportError:
    MockNeo4jClient = None  # type: ignore
    get_mock_client = None  # type: ignore
    close_mock_client = None  # type: ignore

__all__ = [
    "Neo4jClient",
    "Neo4jClientError",
    "MockNeo4jClient",
    "close_neo4j_client",
    "close_mock_client",
    "get_neo4j_client",
    "get_mock_client",
    "transform_paths_to_graph",
]
