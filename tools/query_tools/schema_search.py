import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

from neo4j_client import Neo4jClientError, get_neo4j_client
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class SchemaSearchParams(BaseModel):
    keyword: str = Field(description="Search keyword for table/column name or comment")
    domain: str | None = Field(None, description="Domain code to filter by (e.g., procurement)")


TOOL = {
    "name": "schema_search",
    "display_name": "Schema Search",
    "display_name_locale": {"zh": "图谱内容检索"},
    "description": "Search tables and columns in Neo4j schema graph by keyword and domain",
    "description_locale": {
        "zh": "按关键词和领域在 Neo4j Schema 图中搜索表与字段，返回匹配的表、字段及领域信息"
    },
    "params_model": SchemaSearchParams,
}


def _sanitize(value: str) -> str:
    return value.replace("'", "").replace("\\", "")


async def _search(client: Any, keyword: str, domain: str | None) -> list[dict]:
    if domain:
        domain = _sanitize(domain)
        rows = await client.execute_schema(
            """
            MATCH (t:Table)
            WHERE (t.name CONTAINS $kw OR t.comment CONTAINS $kw)
              AND $domain IN t.domains
            OPTIONAL MATCH (t)-[:HAS_COLUMN]->(c:Column)
            WHERE c.name CONTAINS $kw OR c.comment CONTAINS $kw
            RETURN t.fqn AS table_fqn, t.name AS table_name, t.comment AS table_comment,
                   t.domains AS table_domains,
                   collect(DISTINCT {fqn: c.fqn, name: c.name, comment: c.comment, domains: c.domains}) AS columns
            """,
            {"kw": keyword, "domain": domain},
        )
    else:
        rows = await client.execute_schema(
            """
            MATCH (t:Table)
            WHERE t.name CONTAINS $kw OR t.comment CONTAINS $kw
            OPTIONAL MATCH (t)-[:HAS_COLUMN]->(c:Column)
            WHERE c.name CONTAINS $kw OR c.comment CONTAINS $kw
            RETURN t.fqn AS table_fqn, t.name AS table_name, t.comment AS table_comment,
                   t.domains AS table_domains,
                   collect(DISTINCT {fqn: c.fqn, name: c.name, comment: c.comment, domains: c.domains}) AS columns
            """,
            {"kw": keyword},
        )
    return [
        {
            "table_fqn": r["table_fqn"],
            "table_name": r["table_name"],
            "table_comment": r["table_comment"],
            "domains": r.get("table_domains", []),
            "matched_columns": [c for c in (r.get("columns") or []) if c.get("fqn")],
        }
        for r in rows
    ]


async def execute(args: dict) -> AsyncGenerator[str, None]:
    keyword = args.get("keyword", "")
    domain = args.get("domain")

    if not keyword:
        yield json.dumps({"success": False, "error": "keyword is required"}, ensure_ascii=False)
        return

    try:
        yield json.dumps(
            {"status": "progress", "message": f"Searching for '{keyword}' ..."},
            ensure_ascii=False,
        )

        client = get_neo4j_client()
        results = await _search(client, keyword, domain)

        yield json.dumps(
            {
                "success": True,
                "data": {
                    "keyword": keyword,
                    "domain": domain,
                    "count": len(results),
                    "results": results,
                },
            },
            ensure_ascii=False,
        )

    except Neo4jClientError as e:
        logger.exception("Neo4j error")
        yield json.dumps({"success": False, "error": f"Database error: {e}"}, ensure_ascii=False)
    except Exception as e:
        logger.exception("Schema search error")
        yield json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)
