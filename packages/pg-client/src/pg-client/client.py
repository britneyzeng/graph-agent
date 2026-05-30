"""PostgreSQL Client for async database operations.

This client provides async connection pool for PostgreSQL database,
similar to Neo4jClient for Neo4j database.
"""

from __future__ import annotations

import logging
import re
from threading import Lock
from typing import Any

logger = logging.getLogger(__name__)

_client_lock = Lock()


class PGClientError(Exception):
    """Exception raised for PostgreSQL client errors."""

    pass


class PGClient:
    """Client for async interaction with PostgreSQL database.

    This client wraps asyncpg connection pool and provides
    an interface similar to Neo4jClient.
    """

    def __init__(
        self,
        uri: str,
        user: str,
        password: str,
        schema: str = "public",
        max_pool_size: int = 10,
    ) -> None:
        """Initialize PostgreSQL client.

        Args:
            uri: PostgreSQL connection URI in JDBC format
                (e.g., jdbc:postgresql://host:port/database)
            user: Database username
            password: Database password
            schema: Database schema name (default: public)
            max_pool_size: Maximum connection pool size

        Raises:
            PGClientError: If URI format is invalid
        """
        if not uri or not user or not password:
            raise PGClientError("URI, user, and password must be provided")

        match = re.match(r"jdbc:postgresql://([^:]+):(\d+)/(.+)", uri)
        if not match:
            raise PGClientError(f"Invalid PostgreSQL URI format: {uri}")

        self._host = match.group(1)
        self._port = int(match.group(2))
        self._database = match.group(3)
        self._user = user
        self._password = password
        self._schema = schema
        self._max_pool_size = max_pool_size

        self._pool: Any = None

    async def _get_pool(self) -> Any:
        """Get or create connection pool.

        Returns:
            asyncpg Pool instance
        """
        if self._pool is None:
            try:
                import asyncpg
            except ImportError as e:
                logger.error("asyncpg package not installed: %s", e)
                raise RuntimeError(
                    "asyncpg package is required. Install with: pip install asyncpg"
                ) from e

            self._pool = await asyncpg.create_pool(
                host=self._host,
                port=self._port,
                database=self._database,
                user=self._user,
                password=self._password,
                max_size=self._max_pool_size,
                server_settings={"search_path": self._schema},
            )
            logger.info("[PGClient] Connection pool created")
        return self._pool

    async def execute(
        self,
        query: str,
        parameters: tuple[Any, ...] | None = None,
    ) -> list[dict[str, Any]]:
        """Execute a SQL query and return results as list of dicts.

        Args:
            query: SQL query string with $1, $2 style placeholders
            parameters: Query parameters as tuple

        Returns:
            List of result records as dictionaries

        Raises:
            PGClientError: If query execution fails
        """
        pool = await self._get_pool()

        try:
            async with pool.acquire() as conn:
                if parameters:
                    result = await conn.fetch(query, *parameters)
                else:
                    result = await conn.fetch(query)
                return [dict(row) for row in result]
        except Exception as e:
            logger.exception("[PGClient] Query execution error: %s", e)
            raise PGClientError(f"Query execution failed: {e}") from e

    async def close(self) -> None:
        """Close the connection pool."""
        if self._pool is not None:
            try:
                await self._pool.close()
                logger.info("[PGClient] Connection pool closed")
            except Exception as e:
                logger.warning("[PGClient] Error closing pool: %s", e)
        self._pool = None

    async def __aenter__(self) -> PGClient:
        """Async context manager entry."""
        return self

    async def __aexit__(
        self,
        exc_type: Any,
        exc_val: Any,
        exc_tb: Any,
    ) -> None:
        """Async context manager exit."""
        await self.close()


_pg_client: PGClient | None = None


def get_pg_client() -> PGClient:
    """Get or create the global PostgreSQL client instance.

    The client is configured from environment variables:
        - A20_PG_URI: PostgreSQL connection URI (JDBC format)
        - A20_PG_USER: Database username
        - A20_PG_PASSWORD: Database password
        - A20_PG_SCHEMA: Database schema (default: public)

    Returns:
        PGClient instance

    Raises:
        PGClientError: If required configuration is not set
    """
    global _pg_client
    if _pg_client is None:
        with _client_lock:
            if _pg_client is None:
                import os

                uri = os.getenv("A20_PG_URI")
                user = os.getenv("A20_PG_USER")
                password = os.getenv("A20_PG_PASSWORD")
                schema = os.getenv("A20_PG_SCHEMA", "public")

                if not uri or not user or not password:
                    raise PGClientError(
                        "Required PostgreSQL environment variables not set: "
                        "A20_PG_URI, A20_PG_USER, A20_PG_PASSWORD"
                    )

                _pg_client = PGClient(
                    uri=uri,
                    user=user,
                    password=password,
                    schema=schema,
                )
                logger.info("[PGClient] Client initialized from environment variables")
    return _pg_client


async def close_pg_client() -> None:
    """Close the global PostgreSQL client instance."""
    global _pg_client
    with _client_lock:
        if _pg_client:
            await _pg_client.close()
            _pg_client = None
            logger.info("[PGClient] Client closed")
