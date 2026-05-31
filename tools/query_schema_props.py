"""Query schema properties tool for Neo4j graph database.

This tool queries properties of a specific entity type from Neo4j schema database.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

from neo4j_client import Neo4jClientError, get_neo4j_client
from pydantic import BaseModel, Field

# Setup logging
logger = logging.getLogger(__name__)

# Maximum number of properties to return
MAX_RESULTS = 500000


class QuerySchemaPropsParams(BaseModel):
    """Parameters for query_schema_props tool."""

    entity_type: str = Field(
        description="Entity type (label) to query properties for. Must be a valid Neo4j node label."
    )


TOOL = {
    "name": "query_schema_props",
    "display_name": "Query Schema Properties",
    "display_name_locale": {"zh": "查询图谱实体属性"},
    "description": (
        "Query properties of a specific entity type from Neo4j graph schema database. "
        "Returns property names, types, and optionally Chinese names if available. "
        "Maximum 50 properties."
    ),
    "description_locale": {
        "zh": (
            "从Neo4j图数据库查询指定实体类型下的所有属性信息，最多返回50个属性。"
            "返回属性名称、类型，以及可选的中文名称（如存在）。"
        )
    },
    "params_model": QuerySchemaPropsParams,
}


def _sanitize_identifier(name: str) -> bool:
    """Check if identifier is safe for backtick-quoted Cypher use."""
    if not name or not isinstance(name, str):
        return False
    if "`" in name:
        return False
    return True


def _validate_entity_type(entity_type: str) -> dict[str, Any] | None:
    """Validate entity_type parameter. Returns error dict if invalid."""
    if not entity_type:
        return {"success": False, "error": "错误: entity_type 不能为空"}

    if not _sanitize_identifier(entity_type):
        return {
            "success": False,
            "error": f"错误: entity_type '{entity_type}' 包含非法字符，只允许字母、数字和下划线",
        }

    return None


async def _fetch_entity_properties(
    client: Any,
    entity_type: str,
) -> dict[str, str]:
    """Query properties of a specific entity type from Neo4j schema.

    Args:
        client: Neo4j client instance
        entity_type: Entity type (label) to query

    Returns:
        Dictionary with property name and type mapping (max 50 properties)
    """
    # Query node type properties using Neo4j's schema procedure
    rows = await client.execute_schema(
        """
        CALL db.schema.nodeTypeProperties()
        YIELD nodeType, propertyName, propertyTypes
        RETURN *
        """
    )

    properties: dict[str, str] = {}
    for row in rows:
        node_type = row.get("nodeType")
        # nodeType format is like ":Label" or "`Label`"
        label = node_type.replace(":", "").replace("`", "") if node_type else ""
        prop_name = row.get("propertyName")
        prop_types = row.get("propertyTypes")

        if label == entity_type and prop_name and prop_types:
            prop_type = prop_types[0] if isinstance(prop_types, list) and prop_types else "unknown"
            properties[prop_name] = prop_type
            # Stop when we reach the limit
            if len(properties) >= MAX_RESULTS:
                break

    return properties


async def _fetch_entity_cn_names(
    client: Any,
    entity_type: str,
) -> dict[str, str | None]:
    """Query Chinese names for properties of a specific entity type.

    Args:
        client: Neo4j client instance
        entity_type: Entity type (label) to query

    Returns:
        Dictionary mapping property names to their Chinese names (if available)
    """
    # Try to get a sample node to extract Chinese name
    try:
        rows = await client.execute_schema(
            f"""
            MATCH (n:`{entity_type}`)
            RETURN n
            LIMIT 1
            """
        )

        if not rows:
            return {}

        node_data = rows[0].get("n")
        if not node_data:
            return {}

        properties = node_data if isinstance(node_data, dict) else dict(node_data)

        # Collect all properties ending with _cn (Chinese metadata)
        cn_names: dict[str, str | None] = {}
        for prop_name in properties:
            if prop_name.endswith("_cn"):
                cn_names[prop_name] = str(properties.get(prop_name) or "")

        return cn_names

    except Exception as e:
        logger.warning("Failed to fetch CN names for entity_type %s: %s", entity_type, e)
        return {}


async def execute(args: dict) -> AsyncGenerator[str, None]:
    """Query properties of a specific entity type from Neo4j graph schema.

    Args:
        args: Dictionary containing:
            - entity_type: Entity type (label) to query properties for

    Yields:
        JSON strings with progress messages and final properties result (max 50 properties)
    """
    entity_type = args.get("entity_type", "")

    try:
        yield json.dumps(
            {"status": "progress", "message": f"正在查询实体类型 '{entity_type}' 的属性..."},
            ensure_ascii=False,
        )

        # Validate entity_type
        error = _validate_entity_type(entity_type)
        if error:
            yield json.dumps(error, ensure_ascii=False)
            return

        client = get_neo4j_client()

        # Fetch properties (limited to 50)
        properties = await _fetch_entity_properties(client, entity_type)

        if not properties:
            yield json.dumps(
                {
                    "success": True,
                    "data": {
                        "entity_type": entity_type,
                        "properties": {},
                        "count": 0,
                        "message": f"实体类型 '{entity_type}' 未找到属性定义，可能该类型不存在",
                    },
                },
                ensure_ascii=False,
            )
            return

        yield json.dumps(
            {
                "status": "progress",
                "message": f"发现 {len(properties)} 个属性（最多显示 {MAX_RESULTS} 个）",
            },
            ensure_ascii=False,
        )

        # Try to get Chinese names for properties
        cn_names = await _fetch_entity_cn_names(client, entity_type)

        # Build properties output with CN names
        props_with_cn: list[dict[str, Any]] = []
        for prop_name, prop_type in properties.items():
            prop_info = {
                "name": prop_name,
                "type": prop_type,
            }
            # If this property has a _cn counterpart, include it
            cn_key = f"{prop_name}_cn"
            if cn_key in cn_names:
                prop_info["name_cn"] = cn_names[cn_key]
            props_with_cn.append(prop_info)

        yield json.dumps(
            {
                "success": True,
                "data": {
                    "entity_type": entity_type,
                    "properties": props_with_cn,
                    "count": len(props_with_cn),
                    "limit_applied": MAX_RESULTS,
                },
            },
            ensure_ascii=False,
        )

    except Neo4jClientError as e:
        logger.exception("Neo4j client error: %s", e)
        yield json.dumps({"success": False, "error": f"数据库连接错误: {e}"}, ensure_ascii=False)
    except Exception as e:
        logger.exception("查询Neo4j实体属性异常: %s", e)
        yield json.dumps(
            {"success": False, "error": f"查询实体属性异常: {str(e)}"}, ensure_ascii=False
        )
