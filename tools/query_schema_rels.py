"""Query schema relationships tool for Kuzu graph database.

This tool queries relationship patterns between entity types from Kuzu schema database.
"""

import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

from pydantic import BaseModel, Field

from kuzu_client import KuzuClientError, get_kuzu_client

# Setup logging
logger = logging.getLogger(__name__)

# Maximum number of results to return
MAX_RESULTS = 500000


class QuerySchemaRelsParams(BaseModel):
    """Parameters for query_schema_rels tool."""

    entity_type: str | None = Field(
        default=None,
        description=(
            "Optional entity type (label) to filter related entities. "
            "If provided, returns relationships connected to this entity type. "
            "If not provided, returns all relationship patterns."
        ),
    )
    direction: str = Field(
        default="both",
        description=(
            "Relationship direction filter when entity_type is provided: "
            "'out' - outgoing relationships from entity_type, "
            "'in' - incoming relationships to entity_type, "
            "'both' - both directions (default)"
        ),
    )


TOOL = {
    "name": "query_schema_rels",
    "display_name": "Query Schema Relationships",
    "display_name_locale": {"zh": "查询图谱关系结构"},
    "description": (
        "Query relationship patterns between entity types from Kuzu graph schema database. "
        "Returns relationship patterns without property details. "
        "Can filter by specific entity type and direction. "
        "Maximum 50 results."
    ),
    "description_locale": {
        "zh": (
            "从Kuzu图数据库查询实体类型之间的关系模式，不包含属性信息，最多返回50条结果。"
            "支持按指定实体类型和方向过滤关系网络。"
        )
    },
    "params_model": QuerySchemaRelsParams,
}


def _sanitize_identifier(name: str) -> bool:
    """Check if identifier is safe (only alphanumeric and underscore)."""
    if not name or not isinstance(name, str):
        return False
    return name.replace("_", "").isalnum()


def _validate_entity_type(entity_type: str | None) -> dict[str, Any] | None:
    """Validate entity_type parameter. Returns error dict if invalid."""
    if entity_type and not _sanitize_identifier(entity_type):
        return {
            "success": False,
            "error": (f"错误: entity_type '{entity_type}' 包含非法字符，只允许字母、数字和下划线"),
        }
    return None


_EXCLUDED_RELS = frozenset({"IN_DOMAIN", "HAS_PROPERTY", "REFERENCES"})


async def _fetch_rel_patterns(
    client: Any,
    entity_type: str | None = None,
    direction: str = "both",
) -> list[dict[str, str]]:
    """Query relationship patterns from Kuzu schema.

    Discovers custom rel tables from show_tables(), then queries
    Entity→Entity patterns with entity_type values as source/target.

    Args:
        client: Kuzu client instance
        entity_type: Optional entity type to filter relationships
        direction: Direction filter ('both', 'out', 'in')

    Returns:
        List of relationship patterns with source, target, rel_type
    """
    # Get all rel table names, excluding built-in ones
    rows = await client.execute_schema("CALL show_tables() RETURN name, type")
    rel_tables = [
        r.get("name") for r in rows
        if r.get("type") == "REL" and r.get("name") not in _EXCLUDED_RELS
    ]

    seen: set[tuple[str, str, str]] = set()
    rels: list[dict[str, str]] = []

    for rel_table in rel_tables:
        try:
            query_parts = [f"MATCH (s:Entity)-[r:{rel_table}]->(t:Entity)"]
            params: dict[str, str] = {}

            if entity_type:
                if direction == "out":
                    query_parts.append("WHERE s.entity_type = $type")
                    params["type"] = entity_type
                elif direction == "in":
                    query_parts.append("WHERE t.entity_type = $type")
                    params["type"] = entity_type
                else:
                    query_parts.append("WHERE s.entity_type = $type OR t.entity_type = $type")
                    params["type"] = entity_type

            query_parts.append(
                "RETURN DISTINCT s.entity_type AS source, t.entity_type AS target LIMIT 50"
            )

            result_rows = await client.execute_schema(" ".join(query_parts), params)
            for row in result_rows:
                source = row.get("source")
                target = row.get("target")
                if not source or not target:
                    continue
                key = (source, rel_table, target)
                if key not in seen:
                    seen.add(key)
                    rels.append({"source": source, "target": target, "rel_type": rel_table})
                    if len(rels) >= MAX_RESULTS:
                        return rels

        except Exception as e:
            logger.warning("Failed to query rel table %s: %s", rel_table, e)
            continue

    return rels[:MAX_RESULTS]


async def execute(args: dict) -> AsyncGenerator[str, None]:
    """Query relationship patterns from Kuzu graph schema.

    Args:
        args: Dictionary containing:
            - entity_type: Optional entity type (label) to filter related entities
            - direction: Direction filter ('both', 'out', 'in')

    Yields:
        JSON strings with progress messages and final relationship patterns result
    """
    entity_type = args.get("entity_type")
    direction = args.get("direction", "both")

    try:
        yield json.dumps(
            {"status": "progress", "message": "正在查询图谱关系结构..."}, ensure_ascii=False
        )

        # Validate parameters
        if direction not in ("both", "out", "in"):
            yield json.dumps(
                {
                    "success": False,
                    "error": (
                        f"错误: direction 参数必须是 'both', 'out' 或 'in'，当前值为 '{direction}'"
                    ),
                },
                ensure_ascii=False,
            )
            return

        error = _validate_entity_type(entity_type)
        if error:
            yield json.dumps(error, ensure_ascii=False)
            return

        client = get_kuzu_client()

        # Build query message
        if entity_type:
            yield json.dumps(
                {
                    "status": "progress",
                    "message": (
                        f"正在查询与 '{entity_type}' 相关的节点关系网络（方向: {direction})..."
                    ),
                },
                ensure_ascii=False,
            )
        else:
            yield json.dumps(
                {"status": "progress", "message": "正在查询所有节点关系网络..."},
                ensure_ascii=False,
            )

        # Fetch relationship patterns
        rels = await _fetch_rel_patterns(client, entity_type, direction)

        yield json.dumps(
            {
                "status": "progress",
                "message": f"发现 {len(rels)} 个关系模式（最多显示 {MAX_RESULTS} 个）",
            },
            ensure_ascii=False,
        )

        yield json.dumps(
            {
                "success": True,
                "data": {
                    "rels": rels,
                    "entity_type": entity_type,
                    "direction": direction,
                    "limit_applied": MAX_RESULTS,
                },
            },
            ensure_ascii=False,
        )

    except KuzuClientError as e:
        logger.exception("Kuzu client error: %s", e)
        yield json.dumps({"success": False, "error": f"数据库连接错误: {e}"}, ensure_ascii=False)
    except Exception as e:
        logger.exception("查询Kuzu关系结构异常: %s", e)
        yield json.dumps(
            {"success": False, "error": f"查询关系结构异常: {str(e)}"}, ensure_ascii=False
        )
