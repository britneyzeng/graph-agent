"""Query schema data tool for Kuzu graph database.

This tool queries all entity types and their Chinese names from Kuzu Entity table.
"""

import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

from pydantic import BaseModel

from kuzu_client import KuzuClientError, get_kuzu_client

# Setup logging
logger = logging.getLogger(__name__)

# Maximum number of results to return
MAX_RESULTS = 500000


class QuerySchemaDataParams(BaseModel):
    """Parameters for query_schema_data tool (no parameters required)."""

    pass


TOOL = {
    "name": "query_schema_data",
    "display_name": "Query Schema Data",
    "display_name_locale": {"zh": "查询实体类型"},
    "description": (
        "Query all entity types and their Chinese names from the Entity table. "
        "Maximum 50 results."
    ),
    "description_locale": {
        "zh": "从Entity表中查询所有不同的实体类型及其对应的中文名称。最多返回50条结果。",
    },
    "params_model": QuerySchemaDataParams,
}


async def _fetch_entity_types_with_cn_name(client: Any) -> list[dict[str, Any]]:
    """Query all distinct entity_type values with Chinese names from Entity table.

    Returns entity types with entity_type and name_cn if available.
    Maximum 50 results.
    """
    # Query distinct entity_type values
    rows = await client.execute_schema(
        "MATCH (n:Entity) RETURN DISTINCT n.entity_type AS label ORDER BY label LIMIT 50"
    )
    entity_types = [row.get("label") for row in rows if row.get("label")]

    # Apply maximum limit
    entity_types = entity_types[:MAX_RESULTS]

    # For each entity type, check if there's a representative node with name_cn
    result: list[dict[str, Any]] = []
    for entity_type_val in entity_types:
        try:
            sample_rows = await client.execute_schema(
                """
                MATCH (n:Entity)
                WHERE n.entity_type = $type AND n.name_cn IS NOT NULL
                RETURN n.name_cn as name_cn
                LIMIT 1
                """,
                {"type": entity_type_val},
            )
            name_cn = None
            if sample_rows and sample_rows[0].get("name_cn"):
                name_cn = sample_rows[0].get("name_cn")

            result.append(
                {
                    "label": entity_type_val,
                    "name_cn": name_cn,
                }
            )
        except Exception as e:
            logger.warning("Failed to query name_cn for entity_type %s: %s", entity_type_val, e)
            result.append(
                {
                    "label": entity_type_val,
                    "name_cn": None,
                }
            )

    return result


async def execute(args: dict) -> AsyncGenerator[str, None]:
    """Query Kuzu entity types and Chinese names.

    Args:
        args: Empty dictionary (no parameters required)

    Yields:
        JSON strings with progress messages and final result with entity types list (max 50)
    """
    try:
        yield json.dumps(
            {"status": "progress", "message": "正在查询实体类型..."}, ensure_ascii=False
        )

        client = get_kuzu_client()

        entity_types = await _fetch_entity_types_with_cn_name(client)

        yield json.dumps(
            {
                "status": "progress",
                "message": f"发现 {len(entity_types)} 个实体类型（最多显示 {MAX_RESULTS} 个）",
            },
            ensure_ascii=False,
        )

        yield json.dumps(
            {
                "success": True,
                "data": {
                    "nodes": entity_types,
                    "count": len(entity_types),
                    "limit_applied": MAX_RESULTS,
                },
            },
            ensure_ascii=False,
        )

    except KuzuClientError as e:
        logger.exception("Kuzu client error: %s", e)
        yield json.dumps({"success": False, "error": f"数据库连接错误: {e}"}, ensure_ascii=False)
    except Exception as e:
        logger.exception("查询实体类型异常: %s", e)
        yield json.dumps(
            {"success": False, "error": f"查询实体类型异常: {str(e)}"}, ensure_ascii=False
        )
