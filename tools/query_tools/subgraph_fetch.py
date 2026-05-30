import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

from neo4j_client import Neo4jClientError, get_neo4j_client
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class SubgraphFetchParams(BaseModel):
    domain: str = Field(description="Domain code (e.g., procurement)")
    include_relationships: bool = Field(True, description="Whether to include relationship edges")


TOOL = {
    "name": "subgraph_fetch",
    "display_name": "Subgraph Fetch",
    "display_name_locale": {"zh": "领域子图抽取"},
    "description": "Extract the full subgraph for a given domain, including tables, columns, and their relationships",
    "description_locale": {
        "zh": "按领域 code 抽取完整子图，返回该领域下所有表、字段及之间的关系"
    },
    "params_model": SubgraphFetchParams,
}


async def _sanitize(value: str) -> str:
    return value.replace("'", "").replace("\\", "")


async def execute(args: dict) -> AsyncGenerator[str, None]:
    domain = args.get("domain", "")
    include_rels = args.get("include_relationships", True)

    if not domain:
        yield json.dumps({"success": False, "error": "domain is required"}, ensure_ascii=False)
        return

    try:
        yield json.dumps(
            {"status": "progress", "message": f"Fetching subgraph for domain '{domain}' ..."},
            ensure_ascii=False,
        )

        client = get_neo4j_client()

        domain = _sanitize(domain)

        nodes_query = """
            MATCH (c:Column)
            WHERE $domain IN c.domains
            MATCH (t:Table)-[:HAS_COLUMN]->(c)
            RETURN DISTINCT
                t.fqn AS table_fqn, t.name AS table_name, t.comment AS table_comment,
                c.fqn AS col_fqn, c.name AS col_name, c.data_type AS col_type,
                c.is_pk AS is_pk, c.is_fk AS is_fk
        """
        nodes = await client.execute_schema(nodes_query, {"domain": domain})

        result = {"nodes": [], "relationships": []}
        table_map: dict[str, dict] = {}

        for r in nodes:
            tfqn = r["table_fqn"]
            if tfqn not in table_map:
                table_map[tfqn] = {
                    "fqn": tfqn,
                    "name": r["table_name"],
                    "comment": r.get("table_comment", ""),
                    "columns": [],
                }
            table_map[tfqn]["columns"].append(
                {
                    "fqn": r["col_fqn"],
                    "name": r["col_name"],
                    "data_type": r.get("col_type", ""),
                    "is_pk": r.get("is_pk", False),
                    "is_fk": r.get("is_fk", False),
                }
            )

        result["nodes"] = list(table_map.values())

        if include_rels:
            rels_query = """
                MATCH (c1:Column)
                WHERE $domain IN c1.domains
                MATCH (c1)-[r]-(c2:Column)
                WHERE $domain IN c2.domains
                RETURN DISTINCT
                    c1.fqn AS src_fqn, c2.fqn AS dst_fqn,
                    type(r) AS rel_type,
                    r.frequency AS frequency, r.confidence AS confidence
            """
            rels = await client.execute_schema(rels_query, {"domain": domain})
            result["relationships"] = [
                {
                    "src_fqn": r["src_fqn"],
                    "dst_fqn": r["dst_fqn"],
                    "rel_type": r["rel_type"],
                    "properties": {
                        k: v for k, v in r.items() if k not in ("src_fqn", "dst_fqn", "rel_type") and v is not None
                    },
                }
                for r in rels
            ]

        yield json.dumps(
            {
                "success": True,
                "data": {
                    "domain": domain,
                    "table_count": len(result["nodes"]),
                    "relationship_count": len(result["relationships"]),
                    "subgraph": result,
                },
            },
            ensure_ascii=False,
        )

    except Neo4jClientError as e:
        logger.exception("Neo4j error")
        yield json.dumps({"success": False, "error": f"Database error: {e}"}, ensure_ascii=False)
    except Exception as e:
        logger.exception("Subgraph fetch error")
        yield json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)
