"""Query schema relationships tool for Neo4j graph database.

This tool queries relationship patterns between entity types from Neo4j schema database.
"""

import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

from pydantic import BaseModel, Field

from neo4j_client import Neo4jClientError, get_neo4j_client

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
        "Query relationship patterns between entity types from Neo4j graph schema database. "
        "Returns relationship patterns without property details. "
        "Can filter by specific entity type and direction. "
        "Maximum 50 results."
    ),
    "description_locale": {
        "zh": (
            "从Neo4j图数据库查询实体类型之间的关系模式，不包含属性信息，最多返回50条结果。"
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


async def _fetch_rel_patterns(
    client: Any,
    entity_type: str | None = None,
    direction: str = "both",
) -> list[dict[str, str]]:
    """Query relationship patterns from Neo4j schema.

    Args:
        client: Neo4j client instance
        entity_type: Optional entity type to filter relationships
        direction: Direction filter ('both', 'out', 'in')

    Returns:
        List of relationship patterns with source, target, rel_type
    """
    query_parts = ["MATCH (s)-[r]->(t)"]
    where_conditions = []

    if entity_type:
        if direction == "out":
            where_conditions.append(f"labels(s)[0] = '{entity_type}'")
        elif direction == "in":
            where_conditions.append(f"labels(t)[0] = '{entity_type}'")
        else:
            where_conditions.append(
                f"(labels(s)[0] = '{entity_type}' OR labels(t)[0] = '{entity_type}')"
            )

    if where_conditions:
        query_parts.append("WHERE " + " AND ".join(where_conditions))

    query_parts.append(
        "WITH DISTINCT labels(s)[0] AS source, type(r) AS rel_type, labels(t)[0] AS target "
        f"RETURN source, rel_type, target LIMIT {MAX_RESULTS}"
    )

    query = " ".join(query_parts)
    rows = await client.execute_schema(query)

    rels: list[dict[str, str]] = []
    for row in rows:
        source = row.get("source")
        target = row.get("target")
        rel_type = row.get("rel_type")
        if source and target and rel_type:
            rels.append({"source": source, "target": target, "rel_type": rel_type})

    return rels[:MAX_RESULTS]


async def execute(args: dict) -> AsyncGenerator[str, None]:
    """Query relationship patterns from Neo4j graph schema.

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

        client = get_neo4j_client()

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

    except Neo4jClientError as e:
        logger.exception("Neo4j client error: %s", e)
        yield json.dumps({"success": False, "error": f"数据库连接错误: {e}"}, ensure_ascii=False)
    except Exception as e:
        logger.exception("查询Neo4j关系结构异常: %s", e)
        yield json.dumps(
            {"success": False, "error": f"查询关系结构异常: {str(e)}"}, ensure_ascii=False
        )
