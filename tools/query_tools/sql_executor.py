import json
import logging
from collections.abc import AsyncGenerator

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class SqlExecutorParams(BaseModel):
    sql: str = Field(description="Read-only SQL query to execute against the business PostgreSQL database")
    limit: int = Field(100, description="Maximum number of rows to return")


TOOL = {
    "name": "sql_executor",
    "display_name": "SQL Executor",
    "display_name_locale": {"zh": "实例数据查询"},
    "description": "Execute a read-only SQL query against the business PostgreSQL database to fetch actual instance data",
    "description_locale": {
        "zh": "在业务 PostgreSQL 库上执行只读 SQL 查询，获取真实的实例数据。仅允许 SELECT 语句。"
    },
    "params_model": SqlExecutorParams,
}

ALLOWED_KEYWORDS = {"select", "with", "explain", "analyze"}


async def execute(args: dict) -> AsyncGenerator[str, None]:
    sql = args.get("sql", "").strip()
    limit = min(args.get("limit", 100), 1000)

    if not sql:
        yield json.dumps({"success": False, "error": "SQL is required"}, ensure_ascii=False)
        return

    sql_upper = sql.upper().strip()
    if not any(sql_upper.startswith(kw.upper()) for kw in ALLOWED_KEYWORDS):
        yield json.dumps(
            {"success": False, "error": "Only SELECT queries are allowed"},
            ensure_ascii=False,
        )
        return

    if ";" in sql.rstrip(";") and len(sql.split(";")) > 2:
        yield json.dumps(
            {"success": False, "error": "Multiple statements are not allowed"},
            ensure_ascii=False,
        )
        return

    try:
        clean_sql = sql.rstrip(";")
        if "LIMIT" not in clean_sql.upper():
            clean_sql += f" LIMIT {limit}"

        yield json.dumps(
            {"status": "progress", "message": "Executing query ..."},
            ensure_ascii=False,
        )

        try:
            from pg_client import PGClientError, get_pg_client
        except ImportError:
            yield json.dumps(
                {"success": False, "error": "pg_client package not available"},
                ensure_ascii=False,
            )
            return

        client = get_pg_client()
        rows = await client.execute(clean_sql)

        columns = list(rows[0].keys()) if rows else []
        data = [list(r.values()) for r in rows]

        yield json.dumps(
            {
                "success": True,
                "data": {
                    "sql": sql,
                    "row_count": len(rows),
                    "columns": columns,
                    "rows": data,
                },
            },
            ensure_ascii=False,
        )

    except PGClientError as e:
        logger.exception("PG query error")
        yield json.dumps({"success": False, "error": f"Query error: {e}"}, ensure_ascii=False)
    except Exception as e:
        logger.exception("SQL executor error")
        yield json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)
