"""Query schema data tool for Kuzu graph database.

This tool queries entity types, logic types, or relationship types from Kuzu graph.
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

_VALID_QUERY_TYPES = frozenset({"entity", "logic", "domain", "relation"})


class QuerySchemaDataParams(BaseModel):
    """Parameters for query_schema_data tool."""

    query_type: str = Field(
        default="entity",
        description=(
            "Type of schema data to query: "
            "'entity' - entity types with Chinese names, "
            "'logic' - logic types with Chinese names, "
            "'domain' - domains with Chinese names, "
            "'relation' - relationship table types. "
            "Default is 'entity'."
        ),
    )


TOOL = {
    "name": "query_schema_data",
    "display_name": "Query Schema Data",
    "display_name_locale": {"zh": "查询图谱类型数据"},
    "description": (
        "Query schema data from the Kuzu graph: entity types, logic types, "
        "domains, or relation types. Maximum 50 results."
    ),
    "description_locale": {
        "zh": (
            "从Kuzu图数据库中查询类型数据：实体类型、逻辑类型、领域或关系类型。"
            "最多返回50条结果。"
        ),
    },
    "params_model": QuerySchemaDataParams,
}


async def _fetch_types_with_cn_name(
    client: Any,
    node_label: str,
    type_prop: str,
) -> list[dict[str, Any]]:
    rows = await client.execute_schema(
        f"MATCH (n:{node_label}) RETURN DISTINCT n.{type_prop} AS label ORDER BY label LIMIT 50"
    )
    labels = [row.get("label") for row in rows if row.get("label")]
    labels = labels[:MAX_RESULTS]

    result: list[dict[str, Any]] = []
    for val in labels:
        try:
            sample_rows = await client.execute_schema(
                f"""
                MATCH (n:{node_label})
                WHERE n.{type_prop} = $v AND n.name_cn IS NOT NULL
                RETURN n.name_cn as name_cn
                LIMIT 1
                """,
                {"v": val},
            )
            name_cn = sample_rows[0].get("name_cn") if sample_rows else None
            result.append({"label": val, "name_cn": name_cn})
        except Exception as e:
            logger.warning("Failed to query name_cn for %s %s: %s", node_label, val, e)
            result.append({"label": val, "name_cn": None})

    return result


async def _fetch_relation_types(client: Any) -> list[dict[str, Any]]:
    _REL_NODE_LABELS: dict[str, tuple[str, str]] = {
        "COMPUTES": ("Logic", "Field"),
        "DECOMPOSES_TO": ("Logic", "Logic"),
        "FIELD_LINK": ("Field", "Field"),
        "ENTITY_LINK": ("Entity", "Entity"),
        "DOMAIN_LINK": ("Domain", "Domain"),
        "USE_LOGIC": ("Entity", "Logic"),
        "HAS_LOGIC": ("Domain", "Logic"),
    }

    rows = await client.execute_schema("CALL show_tables() RETURN name, type")
    result: list[dict[str, Any]] = []
    for r in rows:
        if r.get("type") != "REL":
            continue
        name = r.get("name")
        if name == "HAS_PROPERTY":
            continue
        labels = _REL_NODE_LABELS.get(name)
        if labels:
            result.append({"label": name, "from_type": labels[0], "to_type": labels[1]})
        else:
            result.append({"label": name, "from_type": "?", "to_type": "?"})

    return result


async def execute(args: dict) -> AsyncGenerator[str, None]:
    """Query schema data from Kuzu graph.

    Args:
        args: Dictionary containing:
            - type: 'entity' (default), 'logic', or 'relation'

    Yields:
        JSON strings with progress messages and final result
    """
    query_type = args.get("query_type", "entity")

    try:
        if query_type not in _VALID_QUERY_TYPES:
            yield json.dumps(
                {
                    "success": False,
                    "error": (
                        f"错误: query_type 参数必须是 "
                        f"'entity', 'logic', 'domain', 'relation'，"
                        f"当前值为 '{query_type}'"
                    ),
                },
                ensure_ascii=False,
            )
            return

        messages = {
            "entity": "正在查询实体类型...",
            "logic": "正在查询逻辑类型...",
            "domain": "正在查询领域...",
            "relation": "正在查询关系类型...",
        }
        yield json.dumps({"status": "progress", "message": messages[query_type]}, ensure_ascii=False)

        client = get_kuzu_client()

        if query_type == "entity":
            items = await _fetch_types_with_cn_name(client, "Entity", "entity_type")
        elif query_type == "logic":
            items = await _fetch_types_with_cn_name(client, "Logic", "logic_type")
        elif query_type == "domain":
            items = await _fetch_types_with_cn_name(client, "Domain", "fqn")
        else:
            items = await _fetch_relation_types(client)

        yield json.dumps(
            {
                "status": "progress",
                "message": f"发现 {len(items)} 个类型（最多显示 {MAX_RESULTS} 个）",
            },
            ensure_ascii=False,
        )

        yield json.dumps(
            {
                "success": True,
                "data": {
                    "type": query_type,
                    "nodes": items,
                    "count": len(items),
                    "limit_applied": MAX_RESULTS,
                },
            },
            ensure_ascii=False,
        )

    except KuzuClientError as e:
        logger.exception("Kuzu client error: %s", e)
        yield json.dumps({"success": False, "error": f"数据库连接错误: {e}"}, ensure_ascii=False)
    except Exception as e:
        logger.exception("查询类型数据异常: %s", e)
        yield json.dumps(
            {"success": False, "error": f"查询类型数据异常: {str(e)}"}, ensure_ascii=False
        )
