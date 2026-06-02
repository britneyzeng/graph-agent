"""Query schema relationships tool for Kuzu graph database.

This tool queries relationship patterns between node types from Kuzu schema database.
Supports filtering by a start node of any type (Entity, Logic, Domain, Field).
"""

import json
import logging
import re
from collections.abc import AsyncGenerator
from typing import Any

from pydantic import BaseModel, Field

from kuzu_client import KuzuClientError, get_kuzu_client

# Setup logging
logger = logging.getLogger(__name__)

# Maximum number of results to return
MAX_RESULTS = 500000

# Supported node types for filtering
_VALID_NODE_TYPES = frozenset({"Entity", "Logic", "Domain", "Field"})

# Which property to use as the display identifier for each node label
_IDENTIFIER: dict[str, str] = {
    "Entity": "entity_type",
    "Logic": "fqn",
    "Domain": "fqn",
    "Field": "fqn",
}


class QuerySchemaRelsParams(BaseModel):
    """Parameters for query_schema_rels tool."""

    start_node: str = Field(
        description=(
            "Start node value to find relationships for. "
            "For node_type='Entity', this is the entity_type (e.g. 'supplier'). "
            "For other node types, this is the FQN (e.g. 'proc.supplier_risk_rule')."
        ),
    )
    node_type: str = Field(
        default="Entity",
        description=(
            "Node type of start_node: Entity, Logic, Domain, or Field. "
            "Default is 'Entity'."
        ),
    )
    direction: str = Field(
        default="both",
        description=(
            "Relationship direction filter when start_node is provided: "
            "'out' - outgoing relationships from start_node, "
            "'in' - incoming relationships to start_node, "
            "'both' - both directions (default)"
        ),
    )


TOOL = {
    "name": "query_schema_rels",
    "display_name": "Query Schema Relationships",
    "display_name_locale": {"zh": "查询图谱关系结构"},
    "description": (
        "Query relationship patterns from Kuzu graph schema database for a given node. "
        "Returns relationship patterns without property details. "
        "Maximum 50 results."
    ),
    "description_locale": {
        "zh": (
            "从Kuzu图数据库查询指定节点的关系模式，不包含属性信息，最多返回50条结果。"
            "起始节点可以是Entity、Logic、Domain、Field任意类型。"
        )
    },
    "params_model": QuerySchemaRelsParams,
}


def _sanitize_identifier(name: str) -> bool:
    """Check if identifier is safe (only alphanumeric, underscore, and dots)."""
    if not name or not isinstance(name, str):
        return False
    return bool(re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_.]*", name))


def _validate_start_node(start_node: str, node_type: str) -> dict[str, Any] | None:
    """Validate start_node parameter. Returns error dict if invalid."""
    if not start_node:
        return {"success": False, "error": "错误: start_node 不能为空"}
    if not _sanitize_identifier(start_node):
        return {
            "success": False,
            "error": (f"错误: start_node '{start_node}' 包含非法字符，只允许字母、数字、下划线和点"),
        }
    if node_type not in _VALID_NODE_TYPES:
        return {
            "success": False,
            "error": (
                f"错误: node_type '{node_type}' 无效，必须为 "
                f"{', '.join(sorted(_VALID_NODE_TYPES))}"
            ),
        }
    return None


_EXCLUDED_RELS = frozenset({"HAS_PROPERTY"})

# Known rel table → (from_node_label, to_node_label)
_REL_NODE_LABELS: dict[str, tuple[str, str]] = {
    "COMPUTES": ("Logic", "Field"),
    "DECOMPOSES_TO": ("Logic", "Logic"),
    "FIELD_LINK": ("Field", "Field"),
    "ENTITY_LINK": ("Entity", "Entity"),
    "IN_DOMAIN": ("Entity", "Domain"),
    "DOMAIN_LINK": ("Domain", "Domain"),
    "USE_LOGIC": ("Entity", "Logic"),
    "HAS_LOGIC": ("Domain", "Logic"),
}


async def _fetch_rel_patterns(
    client: Any,
    start_node: str,
    node_type: str = "Entity",
    direction: str = "both",
) -> list[dict[str, str]]:
    rows = await client.execute_schema("CALL show_tables() RETURN name, type")
    rel_tables = [
        r.get("name") for r in rows
        if r.get("type") == "REL" and r.get("name") not in _EXCLUDED_RELS
    ]

    seen: set[tuple[str, str, str]] = set()
    rels: list[dict[str, str]] = []

    def _collect(key: tuple[str, str, str], source: str, target: str) -> None:
        if key not in seen and source and target:
            seen.add(key)
            rels.append({"source": source, "target": target, "rel_type": key[1]})

    for rel_table in rel_tables:
        try:
            labels = _REL_NODE_LABELS.get(rel_table)
            if labels is None:
                continue
            from_label, to_label = labels

            params: dict[str, str] = {"v": start_node}

            if direction != "in" and from_label == node_type:
                src_id = _IDENTIFIER.get(from_label, "fqn")
                dst_id = _IDENTIFIER.get(to_label, "fqn")

                q = (
                    f"MATCH (s:{from_label})-[r:{rel_table}]->(t:{to_label}) "
                    f"WHERE s.{src_id} = $v "
                    f"RETURN DISTINCT s.{src_id} AS source, "
                    f"t.{dst_id} AS target "
                    "LIMIT 50"
                )
                for row in await client.execute_schema(q, params):
                    _collect((row["source"], rel_table, row["target"]), row["source"], row["target"])
                    if len(rels) >= MAX_RESULTS:
                        return rels[:MAX_RESULTS]

            if direction != "out" and to_label == node_type:
                src_id = _IDENTIFIER.get(from_label, "fqn")
                dst_id = _IDENTIFIER.get(to_label, "fqn")

                q = (
                    f"MATCH (s:{from_label})-[r:{rel_table}]->(t:{to_label}) "
                    f"WHERE t.{dst_id} = $v "
                    f"RETURN DISTINCT s.{src_id} AS source, "
                    f"t.{dst_id} AS target "
                    "LIMIT 50"
                )
                for row in await client.execute_schema(q, params):
                    _collect((row["source"], rel_table, row["target"]), row["source"], row["target"])
                    if len(rels) >= MAX_RESULTS:
                        return rels[:MAX_RESULTS]

        except Exception as e:
            logger.warning("Failed to query rel table %s: %s", rel_table, e)
            continue

    return rels[:MAX_RESULTS]


async def execute(args: dict) -> AsyncGenerator[str, None]:
    """Query relationship patterns from Kuzu graph schema.

    Args:
        args: Dictionary containing:
            - start_node: Node value to find relationships for
            - node_type: Node type of start_node (Entity, Logic, Domain, Field)
            - direction: Direction filter ('both', 'out', 'in')

    Yields:
        JSON strings with progress messages and final relationship patterns result
    """
    start_node = args.get("start_node", "")
    node_type = args.get("node_type", "Entity")
    direction = args.get("direction", "both")

    try:
        yield json.dumps(
            {"status": "progress", "message": "正在查询图谱关系结构..."}, ensure_ascii=False
        )

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

        error = _validate_start_node(start_node, node_type)
        if error:
            yield json.dumps(error, ensure_ascii=False)
            return

        client = get_kuzu_client()

        yield json.dumps(
            {
                "status": "progress",
                "message": (
                    f"正在查询与 '{start_node}' (类型: {node_type}) "
                    f"相关的节点关系网络（方向: {direction})..."
                ),
            },
            ensure_ascii=False,
        )

        rels = await _fetch_rel_patterns(client, start_node, node_type, direction)

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
                    "start_node": start_node,
                    "node_type": node_type,
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
