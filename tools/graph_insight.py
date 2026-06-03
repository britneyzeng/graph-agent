from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator

from kuzu_client import KuzuClientError, get_kuzu_client
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


LABEL_MAP = {
    "field": {"label": "Field", "name_attr": "name"},
    "entity": {"label": "Entity", "name_attr": "name_cn"},
}


class GraphInsightParams(BaseModel):
    insight_type: str = Field(
        "centrality",
        description="Type: centrality or community",
    )
    target: str = Field(
        "field",
        description="Target: field (columns) or entity (tables)",
    )
    domain: str | None = Field(None, description="Optional domain filter")
    top_k: int = Field(20, description="Number of top results to return")


TOOL = {
    "name": "graph_insight",
    "display_name": "Graph Insight",
    "display_name_locale": {"zh": "图谱洞察"},
    "description": "Retrieve graph-level insights: PageRank centrality and Louvain community structure",
    "description_locale": {
        "zh": "获取图谱级别的结构洞察：PageRank 中心性、Louvain 社区分布（支持字段级和实体级）"
    },
    "params_model": GraphInsightParams,
}


async def execute(args: dict) -> AsyncGenerator[str, None]:
    insight_type = args.get("insight_type", "centrality")
    target = args.get("target", "field")
    domain = args.get("domain")
    top_k = min(args.get("top_k", 20), 100)

    if target not in LABEL_MAP:
        yield json.dumps({"success": False, "error": f"Invalid target: {target}, must be field or entity"}, ensure_ascii=False)
        return

    try:
        client = get_kuzu_client()

        if insight_type == "community":
            yield await _community(client, target, domain, top_k)
        else:
            yield await _centrality(client, target, domain, top_k)

    except KuzuClientError as e:
        logger.exception("Kuzu error")
        yield json.dumps({"success": False, "error": f"Database error: {e}"}, ensure_ascii=False)
    except Exception as e:
        logger.exception("Graph insight error")
        yield json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


async def _centrality(client, target, domain, top_k):
    info = LABEL_MAP[target]
    label = info["label"]
    name_attr = info["name_attr"]
    domain_filter = f"WHERE '{domain}' IN c.domains " if domain else ""

    query = f"""
        MATCH (c:{label})
        {domain_filter}
        RETURN c.fqn AS fqn, c.{name_attr} AS name,
               c.pagerank AS pagerank
        ORDER BY c.pagerank DESC
        LIMIT {top_k}
    """
    rows = await client.execute_schema(query)
    items = [
        {"fqn": r["fqn"], "name": r["name"], "pagerank": r.get("pagerank")}
        for r in rows
    ]

    return json.dumps(
        {"success": True, "data": {"insight_type": "centrality", "target": target, "domain": domain, "items": items}},
        ensure_ascii=False,
    )


async def _community(client, target, domain, top_k):
    info = LABEL_MAP[target]
    label = info["label"]
    domain_filter = f"WHERE '{domain}' IN t.domains " if domain else ""
    count_attr = f"{target}_count"
    sample_attr = f"sample_{target}s"

    query = f"""
        MATCH (t:{label})
        {domain_filter}
        WHERE t.community_id IS NOT NULL
        RETURN t.community_id AS community_id,
               count(*) AS {count_attr},
               collect(t.fqn) AS {sample_attr}
        ORDER BY {count_attr} DESC
        LIMIT {top_k}
    """
    rows = await client.execute_schema(query)
    communities = [
        {
            "community_id": r["community_id"],
            count_attr: r[count_attr],
            sample_attr: r[sample_attr],
        }
        for r in rows
    ]

    return json.dumps(
        {"success": True, "data": {"insight_type": "community", "target": target, "domain": domain, "communities": communities}},
        ensure_ascii=False,
    )
