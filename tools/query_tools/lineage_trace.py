import json
import logging
from collections.abc import AsyncGenerator

from neo4j_client import Neo4jClientError, get_neo4j_client
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class LineageTraceParams(BaseModel):
    column_fqn: str = Field(description="Fully qualified column name (e.g., proc.public.po_line.line_amt)")
    direction: str = Field("upstream", description="Direction: upstream (where this comes from) or downstream (where it flows to)")
    max_depth: int = Field(3, description="Maximum traversal depth")


TOOL = {
    "name": "lineage_trace",
    "display_name": "Lineage Trace",
    "display_name_locale": {"zh": "数据血缘追溯"},
    "description": "Trace field-level data lineage along DERIVES_FROM relationships in Neo4j",
    "description_locale": {
        "zh": "沿 DERIVES_FROM 关系追溯字段级数据血缘，支持上游（来源）和下游（去向）两个方向"
    },
    "params_model": LineageTraceParams,
}


async def execute(args: dict) -> AsyncGenerator[str, None]:
    column_fqn = args.get("column_fqn", "")
    direction = args.get("direction", "upstream")
    max_depth = min(args.get("max_depth", 3), 10)

    if not column_fqn:
        yield json.dumps({"success": False, "error": "column_fqn is required"}, ensure_ascii=False)
        return

    try:
        yield json.dumps(
            {"status": "progress", "message": f"Tracing {direction} lineage for '{column_fqn}' ..."},
            ensure_ascii=False,
        )

        client = get_neo4j_client()

        rel_pattern = "<-[:DERIVES_FROM]-" if direction == "upstream" else "-[:DERIVES_FROM]->"
        query = f"""
            MATCH path = (start:Column {{fqn: $fqn}}){rel_pattern}(related:Column)
            WHERE length(path) <= $max_depth
            RETURN [n IN nodes(path) | n.fqn] AS fqn_path,
                   [r IN relationships(path) | type(r)] AS rel_path,
                   length(path) AS depth
            ORDER BY depth
        """
        rows = await client.execute_schema(query, {"fqn": column_fqn, "max_depth": max_depth})

        paths = []
        visited_fqns = {column_fqn}
        for r in rows:
            fqn_path = r.get("fqn_path", [])
            paths.append({
                "path": fqn_path,
                "rels": r.get("rel_path", [""])[0] if r.get("rel_path") else "",
                "depth": r.get("depth", 0),
            })
            for f in fqn_path:
                visited_fqns.add(f)

        yield json.dumps(
            {
                "success": True,
                "data": {
                    "column_fqn": column_fqn,
                    "direction": direction,
                    "max_depth": max_depth,
                    "unique_columns_found": len(visited_fqns),
                    "paths": paths,
                },
            },
            ensure_ascii=False,
        )

    except Neo4jClientError as e:
        logger.exception("Neo4j error")
        yield json.dumps({"success": False, "error": f"Database error: {e}"}, ensure_ascii=False)
    except Exception as e:
        logger.exception("Lineage trace error")
        yield json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)
