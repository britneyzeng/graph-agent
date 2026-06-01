from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator

from kuzu_client import KuzuClientError, get_kuzu_client
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class GraphInsightParams(BaseModel):
    insight_type: str = Field(
        "centrality",
        description="Type: centrality (top tables by PageRank), "
                    "community (Louvain community distribution), "
                    "summary (overall graph statistics)",
    )
    domain: str | None = Field(None, description="Optional domain filter")
    top_k: int = Field(20, description="Number of top results to return")


TOOL = {
    "name": "graph_insight",
    "display_name": "Graph Insight",
    "display_name_locale": {"zh": "图谱洞察"},
    "description": "Retrieve graph-level insights: centrality, community structure, and overall statistics",
    "description_locale": {
        "zh": "获取图谱级别的结构洞察：PageRank 中心性、Louvain 社区分布、全图统计概览"
    },
    "params_model": GraphInsightParams,
}


async def execute(args: dict) -> AsyncGenerator[str, None]:
    insight_type = args.get("insight_type", "centrality")
    domain = args.get("domain")
    top_k = min(args.get("top_k", 20), 100)

    try:
        client = get_kuzu_client()

        if insight_type == "summary":
            yield await _summary(client, domain)
        elif insight_type == "community":
            yield await _community(client, domain, top_k)
        else:
            yield await _centrality(client, domain, top_k)

    except KuzuClientError as e:
        logger.exception("Kuzu error")
        yield json.dumps({"success": False, "error": f"Database error: {e}"}, ensure_ascii=False)
    except Exception as e:
        logger.exception("Graph insight error")
        yield json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


async def _centrality(client, domain, top_k):
    label = "Field"
    domain_filter = f"WHERE '{domain}' IN c.domains " if domain else ""

    query = f"""
        MATCH (c:{label})
        {domain_filter}
        RETURN c.fqn AS fqn, c.name AS name,
               c.pagerank AS pagerank,
               c.betweenness AS betweenness
        ORDER BY c.pagerank DESC
        LIMIT {top_k}
    """
    rows = await client.execute_schema(query)
    items = [
        {"fqn": r["fqn"], "name": r["name"], "pagerank": r.get("pagerank"), "betweenness": r.get("betweenness")}
        for r in rows
    ]

    return json.dumps(
        {"success": True, "data": {"insight_type": "centrality", "domain": domain, "items": items}},
        ensure_ascii=False,
    )


async def _community(client, domain, top_k):
    label = "Entity"
    domain_filter = f"WHERE '{domain}' IN t.domains " if domain else ""

    query = f"""
        MATCH (t:{label})
        {domain_filter}
        RETURN t.community_id AS community_id,
               count(*) AS entity_count,
               collect(t.name)[0..10] AS sample_entities
        ORDER BY entity_count DESC
        LIMIT {top_k}
    """
    rows = await client.execute_schema(query)
    communities = [
        {
            "community_id": r.get("community_id"),
            "entity_count": r.get("entity_count", 0),
            "sample_entities": r.get("sample_entities", []),
        }
        for r in rows
        if r.get("community_id") is not None
    ]

    return json.dumps(
        {"success": True, "data": {"insight_type": "community", "domain": domain, "communities": communities}},
        ensure_ascii=False,
    )


async def _summary(client, domain):
    parts = ["MATCH (t:Entity) RETURN count(*) AS entity_count"]
    if domain:
        parts = [f"MATCH (t:Entity) WHERE '{domain}' IN t.domains RETURN count(*) AS entity_count"]

    rows = await client.execute_schema(parts[0])
    entity_count = rows[0]["entity_count"] if rows else 0

    col_query = "MATCH (c:Field) RETURN count(*) AS col_count"
    rows = await client.execute_schema(col_query)
    col_count = rows[0]["col_count"] if rows else 0

    rel_query = "MATCH ()-[r]->() RETURN count(*) AS rel_count"
    rows = await client.execute_schema(rel_query)
    rel_count = rows[0]["rel_count"] if rows else 0

    return json.dumps(
        {
            "success": True,
            "data": {
                "insight_type": "summary",
                "domain": domain,
                "entity_count": entity_count,
                "column_count": col_count,
                "relationship_count": rel_count,
            },
        },
        ensure_ascii=False,
    )
