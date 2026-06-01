"""Query schema properties tool for Kuzu graph database.

This tool queries properties of a specific entity type from Kuzu schema database.
"""

import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

from pydantic import BaseModel, Field

from kuzu_client import KuzuClientError, get_kuzu_client

# Setup logging
logger = logging.getLogger(__name__)

# Maximum number of properties to return
MAX_RESULTS = 500000


class QuerySchemaPropsParams(BaseModel):
    """Parameters for query_schema_props tool."""

    entity_type: str = Field(
        description="Entity type (label) to query properties for. Must be a valid Kuzu node table name."
    )


TOOL = {
    "name": "query_schema_props",
    "display_name": "Query Schema Properties",
    "display_name_locale": {"zh": "查询图谱实体属性"},
    "description": (
        "Query properties of a specific entity type from Kuzu graph schema database. "
        "Returns property names, types, and optionally Chinese names if available. "
        "Maximum 50 properties."
    ),
    "description_locale": {
        "zh": (
            "从Kuzu图数据库查询指定实体类型下的所有属性信息，最多返回50个属性。"
            "返回属性名称、类型，以及可选的中文名称（如存在）。"
        )
    },
    "params_model": QuerySchemaPropsParams,
}


def _sanitize_identifier(name: str) -> bool:
    """Check if identifier is safe (only alphanumeric and underscore)."""
    if not name or not isinstance(name, str):
        return False
    return name.replace("_", "").isalnum()


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
    """Query properties of a specific entity type from Kuzu schema.

    Args:
        client: Kuzu client instance
        entity_type: Entity type (label) to query

    Returns:
        Dictionary with property name and type mapping (max 50 properties)
    """
    # Query Field nodes connected to entities of this type via HAS_PROPERTY
    rows = await client.execute_schema(
        """
        MATCH (e:Entity)-[:HAS_PROPERTY]->(c:Field)
        WHERE e.entity_type = $type
        RETURN DISTINCT c.name AS name, c.data_type AS type
        ORDER BY name
        """,
        {"type": entity_type},
    )

    properties: dict[str, str] = {}
    for row in rows:
        prop_name = row.get("name")
        prop_type = row.get("type")
        if prop_name and prop_type:
            properties[prop_name] = prop_type
            if len(properties) >= MAX_RESULTS:
                break

    return properties


async def execute(args: dict) -> AsyncGenerator[str, None]:
    """Query properties of a specific entity type from Kuzu graph schema.

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

        client = get_kuzu_client()

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

        # Build properties output with CN names
        props_with_cn: list[dict[str, Any]] = []
        for prop_name, prop_type in properties.items():
            prop_info = {
                "name": prop_name,
                "type": prop_type,
            }
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

    except KuzuClientError as e:
        logger.exception("Kuzu client error: %s", e)
        yield json.dumps({"success": False, "error": f"数据库连接错误: {e}"}, ensure_ascii=False)
    except Exception as e:
        logger.exception("查询Kuzu实体属性异常: %s", e)
        yield json.dumps(
            {"success": False, "error": f"查询实体属性异常: {str(e)}"}, ensure_ascii=False
        )
