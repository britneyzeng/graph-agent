from __future__ import annotations

import logging
from typing import Any

import networkx as nx

from analysis import build_graph, get_client

logger = logging.getLogger(__name__)


def run_pagerank_field(domain: str | None = None, write_property: str = "pagerank", **kwargs) -> dict[str, Any]:
    client = get_client()
    if client is None:
        return {"status": "skipped", "reason": "Kuzu client unavailable"}

    G = build_graph(client, "Field", "FIELD_LINK", "field")
    if G.number_of_nodes() == 0:
        return {"status": "skipped", "reason": "No nodes in graph"}

    pr = nx.pagerank(G, alpha=0.85, max_iter=200)
    for fqn, score in pr.items():
        client.execute(
            f"MATCH (c:Field {{fqn: $fqn}}) SET c.{write_property} = $score",
            {"fqn": fqn, "score": score},
        )
    logger.info("Field PageRank completed for %d nodes", len(pr))
    return {"status": "ok", "algo": "pagerank_field", "result": {"nodePropertiesWritten": len(pr), "ranIterations": 200}}


def run_pagerank_entity(domain: str | None = None, write_property: str = "pagerank", **kwargs) -> dict[str, Any]:
    client = get_client()
    if client is None:
        return {"status": "skipped", "reason": "Kuzu client unavailable"}

    G = build_graph(client, "Entity", "ENTITY_LINK", "entity")
    if G.number_of_nodes() == 0:
        return {"status": "skipped", "reason": "No nodes in graph"}

    pr = nx.pagerank(G, alpha=0.85, max_iter=200)
    for fqn, score in pr.items():
        client.execute(
            f"MATCH (e:Entity {{fqn: $fqn}}) SET e.{write_property} = $score",
            {"fqn": fqn, "score": score},
        )
    logger.info("Entity PageRank completed for %d nodes", len(pr))
    return {"status": "ok", "algo": "pagerank_entity", "result": {"nodePropertiesWritten": len(pr), "ranIterations": 200}}
