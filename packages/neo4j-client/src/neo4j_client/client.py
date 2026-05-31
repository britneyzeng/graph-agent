"""Neo4j Client for direct graph database operations.

This client provides direct connections to Neo4j databases, similar to
KGraphClient for Kuzu database. It supports two database connections:
- schema_db: For schema definition queries (neo4j-purioc, port 7683)
- data_db: For business data queries (neo4j-purioc-data, port 7682)
"""

from __future__ import annotations

import logging
from threading import Lock
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from neo4j_client.mock_client import MockNeo4jClient

logger = logging.getLogger(__name__)

_client_lock = Lock()


def _serialize_value(value: Any) -> Any:
    """Serialize Neo4j value to JSON-serializable format.

    Only handles Path objects (converts to alternating node/rel list).
    Other types (Node, Relationship, primitives) are returned as-is,
    to be handled by graph_handler.

    Args:
        value: Value from Neo4j query result

    Returns:
        Serialized value
    """
    # Handle Path objects: convert to alternating [node, rel, node, rel, ...] list
    if hasattr(value, "nodes") and hasattr(value, "relationships"):
        path_list = []
        nodes = list(value.nodes)
        rels = list(value.relationships)
        for i, node in enumerate(nodes):
            path_list.append(node)
            if i < len(rels):
                path_list.append(rels[i])
        return path_list

    return value


class Neo4jClientError(Exception):
    """Exception raised for Neo4j client errors."""

    pass


class Neo4jClient:
    """Client for direct interaction with Neo4j database.

    This client wraps the official neo4j-python async driver and provides
    an interface similar to KGraphClient.

    Supports two database connections:
    - schema_db: For schema/metadata queries
    - data_db: For business data queries
    """

    def __init__(
        self,
        schema_uri: str,
        schema_user: str,
        schema_password: str,
        schema_database: str = "neo4j",
        data_uri: str | None = None,
        data_user: str | None = None,
        data_password: str | None = None,
        data_database: str = "neo4j",
        max_connection_pool_size: int = 50,
        connection_timeout: float = 30.0,
        connection_acquisition_timeout: float = 60.0,
    ) -> None:
        """Initialize Neo4j client with two database connections.

        Args:
            schema_uri: Schema database URI (e.g., neo4j://host:7683)
            schema_user: Schema database username
            schema_password: Schema database password
            schema_database: Schema database name (default: neo4j)
            data_uri: Data database URI (e.g., neo4j://host:7682), defaults to schema_uri
            data_user: Data database username, defaults to schema_user
            data_password: Data database password, defaults to schema_password
            data_database: Data database name (default: neo4j)
            max_connection_pool_size: Maximum connection pool size
            connection_timeout: Connection timeout in seconds
            connection_acquisition_timeout: Timeout for acquiring connection

        Raises:
            Neo4jClientError: If required credentials are missing
        """
        if not schema_uri or not schema_user or not schema_password:
            raise Neo4jClientError("Schema database URI, user, and password must be provided")

        # Schema database configuration
        self._schema_uri = schema_uri
        self._schema_user = schema_user
        self._schema_password = schema_password
        self._schema_database = schema_database

        # Data database configuration (defaults to schema config if not provided)
        self._data_uri = data_uri or schema_uri
        self._data_user = data_user or schema_user
        self._data_password = data_password or schema_password
        self._data_database = data_database

        self._max_connection_pool_size = max_connection_pool_size
        self._connection_timeout = connection_timeout
        self._connection_acquisition_timeout = connection_acquisition_timeout

        self._schema_driver: Any = None
        self._data_driver: Any = None

    def _create_driver(self, uri: str, user: str, password: str) -> Any:
        """Create a Neo4j async driver instance.

        Args:
            uri: Connection URI
            user: Username
            password: Password

        Returns:
            Neo4j async driver instance

        Raises:
            RuntimeError: If neo4j package is not installed
        """
        try:
            from neo4j import AsyncGraphDatabase
        except ImportError as e:
            logger.error("neo4j package not installed: %s", e)
            raise RuntimeError("neo4j package is required. Install with: pip install neo4j") from e

        return AsyncGraphDatabase.driver(
            uri,
            auth=(user, password),
            max_connection_pool_size=self._max_connection_pool_size,
            connection_timeout=self._connection_timeout,
            connection_acquisition_timeout=self._connection_acquisition_timeout,
        )

    def _get_schema_driver(self) -> Any:
        """Get or create driver for schema database.

        Returns:
            Neo4j async driver for schema database
        """
        if self._schema_driver is None:
            self._schema_driver = self._create_driver(
                self._schema_uri,
                self._schema_user,
                self._schema_password,
            )
        return self._schema_driver

    def _get_data_driver(self) -> Any:
        """Get or create driver for data database.

        Returns:
            Neo4j async driver for data database
        """
        if self._data_driver is None:
            self._data_driver = self._create_driver(
                self._data_uri,
                self._data_user,
                self._data_password,
            )
        return self._data_driver

    async def _execute(
        self,
        driver: Any,
        database: str,
        query: str,
        parameters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Execute a Cypher query.

        Args:
            driver: Neo4j async driver to use
            database: Database name
            query: Cypher query string
            parameters: Query parameters

        Returns:
            List of result records as dictionaries

        Raises:
            Neo4jClientError: If query execution fails
        """
        parameters = parameters or {}

        try:
            async with driver.session(database=database) as session:
                result = await session.run(query, parameters)
                records = [
                    {key: _serialize_value(value) for key, value in record.items()}
                    async for record in result
                ]
                return records
        except Exception as e:
            logger.exception("[Neo4jClient] Query execution error: %s", e)
            raise Neo4jClientError(f"Query execution failed: {e}") from e

    async def execute_schema(
        self,
        query: str,
        parameters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Execute a schema query on schema database.

        Args:
            query: Cypher query string
            parameters: Optional query parameters

        Returns:
            List of query results
        """
        return await self._execute(
            self._get_schema_driver(),
            self._schema_database,
            query,
            parameters,
        )

    async def execute_data(
        self,
        query: str,
        parameters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Execute a data query on data database.

        Args:
            query: Cypher query string
            parameters: Optional query parameters

        Returns:
            List of query results
        """
        return await self._execute(
            self._get_data_driver(),
            self._data_database,
            query,
            parameters,
        )

    async def close(self) -> None:
        """Close both Neo4j driver connections."""
        for driver_name, driver in [
            ("schema", self._schema_driver),
            ("data", self._data_driver),
        ]:
            if driver is not None:
                try:
                    await driver.close()
                except Exception as e:
                    logger.warning("[Neo4jClient] Error closing %s driver: %s", driver_name, e)
        self._schema_driver = None
        self._data_driver = None

    async def __aenter__(self) -> Neo4jClient:
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        await self.close()


_neo4j_client: Neo4jClient | None = None


def get_neo4j_client() -> Neo4jClient | MockNeo4jClient:
    """Get or create the global Neo4j client instance.

    When A20_NEO4J_MOCK=1 is set, returns an in-memory MockNeo4jClient
    for local development.  Otherwise connects to a real Neo4j instance
    configured from environment variables:
        - A20_NEO4J_SCHEMA_URI: Schema database URI
        - A20_NEO4J_SCHEMA_USER: Schema database username
        - A20_NEO4J_SCHEMA_PASSWORD: Schema database password
        - A20_NEO4J_SCHEMA_DATABASE: Schema database name (default: neo4j)
        - A20_NEO4J_DATA_URI: Data database URI
        - A20_NEO4J_DATA_USER: Data database username
        - A20_NEO4J_DATA_PASSWORD: Data database password
        - A20_NEO4J_DATA_DATABASE: Data database name (default: neo4j)

    Returns:
        Neo4jClient or MockNeo4jClient instance

    Raises:
        Neo4jClientError: If required configuration is not set
    """
    import os

    if os.getenv("A20_NEO4J_MOCK") == "1":
        from neo4j_client.mock_client import get_mock_client as _get_mock
        return _get_mock()

    global _neo4j_client
    if _neo4j_client is None:
        with _client_lock:
            if _neo4j_client is None:
                schema_uri = os.getenv("A20_NEO4J_SCHEMA_URI")
                schema_user = os.getenv("A20_NEO4J_SCHEMA_USER")
                schema_password = os.getenv("A20_NEO4J_SCHEMA_PASSWORD")

                if not schema_uri or not schema_user or not schema_password:
                    raise Neo4jClientError(
                        "Required Neo4j environment variables not set: "
                        "A20_NEO4J_SCHEMA_URI, A20_NEO4J_SCHEMA_USER, A20_NEO4J_SCHEMA_PASSWORD"
                    )

                _neo4j_client = Neo4jClient(
                    schema_uri=schema_uri,
                    schema_user=schema_user,
                    schema_password=schema_password,
                    schema_database=os.getenv("A20_NEO4J_SCHEMA_DATABASE", "neo4j"),
                    data_uri=os.getenv("A20_NEO4J_DATA_URI"),
                    data_user=os.getenv("A20_NEO4J_DATA_USER"),
                    data_password=os.getenv("A20_NEO4J_DATA_PASSWORD"),
                    data_database=os.getenv("A20_NEO4J_DATA_DATABASE", "neo4j"),
                )
                logger.info("[Neo4jClient] Client initialized from environment variables")
    return _neo4j_client


async def close_neo4j_client() -> None:
    """Close the global Neo4j client instance."""
    import os
    if os.getenv("A20_NEO4J_MOCK") == "1":
        from neo4j_client.mock_client import close_mock_client as _close_mock
        _close_mock()
        return

    global _neo4j_client
    with _client_lock:
        if _neo4j_client:
            await _neo4j_client.close()
            _neo4j_client = None
            logger.info("[Neo4jClient] Client closed")
