from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from queue import Queue
from typing import Any

import kuzu

logger = logging.getLogger(__name__)


class KuzuClientError(Exception):
    pass


class KuzuClient:
    def __init__(self, db_path: str, buffer_pool_size: int = 0, pool_size: int = 8, recreate: bool = True):
        self._db_path = db_path
        db_path_obj = Path(db_path)
        db_path_obj.parent.mkdir(parents=True, exist_ok=True)
        if recreate:
            if db_path_obj.is_dir():
                import shutil
                shutil.rmtree(db_path_obj)
            elif db_path_obj.is_file():
                db_path_obj.unlink()
        self._db = kuzu.Database(db_path, buffer_pool_size=buffer_pool_size)
        self._pool: Queue[kuzu.Connection] = Queue(maxsize=pool_size)
        for _ in range(pool_size):
            self._pool.put(kuzu.Connection(self._db))

    def _get_conn(self) -> kuzu.Connection:
        return self._pool.get()

    def _put_conn(self, conn: kuzu.Connection) -> None:
        self._pool.put(conn)

    def _result_to_dicts(self, result: kuzu.QueryResult) -> list[dict[str, Any]]:
        try:
            columns = result.get_column_names()
            rows = []
            while result.has_next():
                row = result.get_next()
                rows.append(dict(zip(columns, row)))
            return rows
        except Exception as e:
            logger.exception("result_to_dicts error: %s", e)
            raise KuzuClientError(f"Result conversion failed: {e}") from e

    def execute(
        self, query: str, parameters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        parameters = parameters or {}
        conn = self._get_conn()
        try:
            result = conn.execute(query, parameters)
            return self._result_to_dicts(result)
        except Exception as e:
            logger.exception("[KuzuClient] Query error: %s", e)
            raise KuzuClientError(f"Query failed: {e}") from e
        finally:
            self._put_conn(conn)

    async def execute_schema(
        self, query: str, parameters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.execute, query, parameters)

    def close(self) -> None:
        while not self._pool.empty():
            conn = self._pool.get()
            try:
                conn.close()
            except Exception as e:
                logger.warning("Connection close error: %s", e)
        try:
            self._db.close()
        except Exception as e:
            logger.warning("DB close error: %s", e)

    async def __aenter__(self) -> KuzuClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        self.close()


_kuzu_client: KuzuClient | None = None


def get_kuzu_client(*, recreate: bool = False) -> KuzuClient:
    global _kuzu_client
    if _kuzu_client is None:
        db_path = os.getenv("A20_KUZU_DB_PATH", "")
        if not db_path:
            db_path = str(Path.cwd() / "kuzu_db" / "graph.db")
        _kuzu_client = KuzuClient(db_path, recreate=recreate)
        logger.info("[KuzuClient] Initialized at %s (recreate=%s)", db_path, recreate)
    return _kuzu_client


def close_kuzu_client() -> None:
    global _kuzu_client
    if _kuzu_client:
        _kuzu_client.close()
        _kuzu_client = None
        logger.info("[KuzuClient] Closed")
