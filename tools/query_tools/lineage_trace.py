import json
import logging
from collections.abc import AsyncGenerator

from kuzu_client import KuzuClientError, get_kuzu_client
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
    "description": "Trace field-level data lineage along FIELD_LINK relationships",
    "description_locale": {
        "zh": "沿 FIELD_LINK 关系追溯字段级数据血缘，支持上游（来源）和下游（去向）两个方向"
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

        client = get_kuzu_client()

        arrow = "<-" if direction == "upstream" else "-"
        query = f"""
            MATCH path = (start:Field {{fqn: $fqn}}){arrow}[:FIELD_LINK*1..$max_depth]-(related:Field)
            RETURN nodes(path) AS fqn_path,
                   relationships(path) AS rel_path,
                   length(path) AS depth
            ORDER BY depth
        """
        rows = await client.execute_schema(query, {"fqn": column_fqn, "max_depth": max_depth})

        paths = []
        visited_fqns = {column_fqn}
        for r in rows:
            raw_path = r.get("fqn_path", [])
            fqn_path = [n.get("fqn", str(n)) if isinstance(n, dict) else str(n) for n in raw_path] if isinstance(raw_path, list) else []
            raw_rels = r.get("rel_path", [])
            rels = [rel if isinstance(rel, str) else (rel.get("_label", "") if isinstance(rel, dict) else "") for rel in raw_rels] if isinstance(raw_rels, list) else []
            paths.append({
                "path": fqn_path,
                "rels": rels[0] if rels else "",
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

    except KuzuClientError as e:
        logger.exception("Kuzu error")
        yield json.dumps({"success": False, "error": f"Database error: {e}"}, ensure_ascii=False)
    except Exception as e:
        logger.exception("Lineage trace error")
        yield json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)
