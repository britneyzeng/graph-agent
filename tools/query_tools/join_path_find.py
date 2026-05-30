import json
import logging
from collections.abc import AsyncGenerator

from neo4j_client import Neo4jClientError, get_neo4j_client
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class JoinPathFindParams(BaseModel):
    table_a_fqn: str = Field(description="Starting table FQN (e.g., proc.public.po_order)")
    table_b_fqn: str = Field(description="Target table FQN (e.g., proc.public.supplier)")
    max_hops: int = Field(5, description="Maximum number of relationship hops")


TOOL = {
    "name": "join_path_find",
    "display_name": "Join Path Find",
    "display_name_locale": {"zh": "表间 JOIN 路径发现"},
    "description": "Find the shortest JOIN path between two tables via shared columns in Neo4j",
    "description_locale": {
        "zh": "在 Neo4j 图中查找两表间通过共享字段可达的最短 JOIN 路径，辅助自动生成 SQL JOIN 语句"
    },
    "params_model": JoinPathFindParams,
}


async def execute(args: dict) -> AsyncGenerator[str, None]:
    table_a = args.get("table_a_fqn", "")
    table_b = args.get("table_b_fqn", "")
    max_hops = min(args.get("max_hops", 5), 10)

    if not table_a or not table_b:
        yield json.dumps({"success": False, "error": "table_a_fqn and table_b_fqn are required"}, ensure_ascii=False)
        return

    try:
        yield json.dumps(
            {"status": "progress", "message": f"Finding JOIN paths between '{table_a}' and '{table_b}' ..."},
            ensure_ascii=False,
        )

        client = get_neo4j_client()

        query = """
            MATCH (a:Table {fqn: $a_fqn}), (b:Table {fqn: $b_fqn})
            MATCH path = shortestPath(
                (a)-[:HAS_COLUMN]->(:Column)-[:REFERENCES|JOINS_WITH*1..$max_hops]-(:Column)<-[:HAS_COLUMN]-(b)
            )
            RETURN [n IN nodes(path) | labels(n)[0] + ":" + n.fqn] AS node_path,
                   [r IN relationships(path) | type(r)] AS rel_path,
                   length(path) AS hops
        """
        rows = await client.execute_schema(query, {"a_fqn": table_a, "b_fqn": table_b, "max_hops": max_hops})

        paths = []
        for r in rows:
            paths.append(
                {
                    "hops": r.get("hops", 0),
                    "node_path": r.get("node_path", []),
                    "rel_path": r.get("rel_path", []),
                }
            )

        yield json.dumps(
            {
                "success": True,
                "data": {
                    "table_a": table_a,
                    "table_b": table_b,
                    "max_hops": max_hops,
                    "paths_found": len(paths),
                    "paths": paths,
                    "suggestion": (
                        "Use the JOIN path to construct SQL: "
                        + (" -> ".join(p["rel_path"]) for p in paths).__next__()
                        if paths
                        else "No path found"
                    ),
                },
            },
            ensure_ascii=False,
        )

    except Neo4jClientError as e:
        logger.exception("Neo4j error")
        yield json.dumps({"success": False, "error": f"Database error: {e}"}, ensure_ascii=False)
    except Exception as e:
        logger.exception("Join path find error")
        yield json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)
