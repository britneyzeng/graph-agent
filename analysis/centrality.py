from __future__ import annotations

import logging
from typing import Any

import networkx as nx

try:
    from kuzu_client import get_kuzu_client
except ImportError:
    get_kuzu_client = None

logger = logging.getLogger(__name__)


def _get_client():
    try:
        return get_kuzu_client()
    except Exception as e:
        logger.warning("Kuzu client not available: %s", e)
        return None


def _build_column_graph(client) -> nx.Graph:
    G = nx.Graph()
    rows = client.execute(
        "MATCH (c:Field) RETURN c.fqn AS fqn"
    )
    for r in rows:
        G.add_node(r["fqn"])
    rows = client.execute(
        "MATCH (c1:Field)-[r:REFERENCES|JOINS_WITH]-(c2:Field) "
        "RETURN c1.fqn AS src, c2.fqn AS dst"
    )
    for r in rows:
        G.add_edge(r["src"], r["dst"])
    logger.info("Built column graph with %d nodes, %d edges", G.number_of_nodes(), G.number_of_edges())
    return G


def run_pagerank(domain: str | None = None, write_property: str = "pagerank", **kwargs) -> dict[str, Any]:
    client = _get_client()
    if client is None:
        return {"status": "skipped", "reason": "Kuzu client unavailable"}

    G = _build_column_graph(client)
    if G.number_of_nodes() == 0:
        return {"status": "skipped", "reason": "No nodes in graph"}

    pr = nx.pagerank(G, alpha=0.85, max_iter=20)
    client.execute("BEGIN TRANSACTION")
    for fqn, score in pr.items():
        client.execute(
            f"MATCH (c:Field {{fqn: $fqn}}) SET c.{write_property} = $score",
            {"fqn": fqn, "score": score},
        )
    client.execute("COMMIT")
    logger.info("PageRank completed for %d nodes", len(pr))
    return {"status": "ok", "algo": "pagerank", "result": {"nodePropertiesWritten": len(pr), "ranIterations": 20}}


def run_betweenness(domain: str | None = None, write_property: str = "betweenness", **kwargs) -> dict[str, Any]:
    client = _get_client()
    if client is None:
        return {"status": "skipped", "reason": "Kuzu client unavailable"}

    G = _build_column_graph(client)
    if G.number_of_nodes() == 0:
        return {"status": "skipped", "reason": "No nodes in graph"}

    bc = nx.betweenness_centrality(G)
    client.execute("BEGIN TRANSACTION")
    for fqn, score in bc.items():
        client.execute(
            f"MATCH (c:Field {{fqn: $fqn}}) SET c.{write_property} = $score",
            {"fqn": fqn, "score": score},
        )
    client.execute("COMMIT")
    logger.info("Betweenness completed for %d nodes", len(bc))
    return {"status": "ok", "algo": "betweenness", "result": {"nodePropertiesWritten": len(bc)}}


def run_degree(domain: str | None = None, write_property: str = "degree", **kwargs) -> dict[str, Any]:
    client = _get_client()
    if client is None:
        return {"status": "skipped", "reason": "Kuzu client unavailable"}

    G = _build_column_graph(client)
    if G.number_of_nodes() == 0:
        return {"status": "skipped", "reason": "No nodes in graph"}

    dc = nx.degree_centrality(G)
    client.execute("BEGIN TRANSACTION")
    for fqn, score in dc.items():
        client.execute(
            f"MATCH (c:Field {{fqn: $fqn}}) SET c.{write_property} = $score",
            {"fqn": fqn, "score": score},
        )
    client.execute("COMMIT")
    logger.info("Degree centrality completed for %d nodes", len(dc))
    return {"status": "ok", "algo": "degree", "result": {"nodePropertiesWritten": len(dc)}}
