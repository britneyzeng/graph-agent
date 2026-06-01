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
    rows = client.execute("MATCH (c:Field) RETURN c.fqn AS fqn")
    for r in rows:
        G.add_node(r["fqn"])
    rows = client.execute(
        "MATCH (c1:Field)-[r:REFERENCES|JOINS_WITH]-(c2:Field) "
        "RETURN c1.fqn AS src, c2.fqn AS dst"
    )
    for r in rows:
        G.add_edge(r["src"], r["dst"])
    return G


def run_louvain(
    domain: str | None = None,
    resolution: float = 1.0,
    write_property: str = "community_id",
    **kwargs,
) -> dict[str, Any]:
    client = _get_client()
    if client is None:
        return {"status": "skipped", "reason": "Kuzu client unavailable"}

    G = _build_column_graph(client)
    if G.number_of_nodes() == 0:
        return {"status": "skipped", "reason": "No nodes in graph"}

    communities = nx.community.louvain_communities(G, resolution=resolution, seed=42)
    node_to_cid: dict[str, int] = {}
    for cid, comm in enumerate(communities):
        for node in comm:
            node_to_cid[node] = cid

    client.execute("BEGIN TRANSACTION")
    for fqn, cid in node_to_cid.items():
        client.execute(
            f"MATCH (c:Field {{fqn: $fqn}}) SET c.{write_property} = $cid",
            {"fqn": fqn, "cid": cid},
        )
    client.execute("COMMIT")
    logger.info("Louvain completed: %d communities", len(communities))
    return {
        "status": "ok",
        "algo": "louvain",
        "result": {
            "communityCount": len(communities),
            "modularity": 0.0,
            "ranLevels": 0,
            "nodePropertiesWritten": len(node_to_cid),
        },
    }


def run_wcc(domain: str | None = None, **kwargs) -> dict[str, Any]:
    client = _get_client()
    if client is None:
        return {"status": "skipped", "reason": "Kuzu client unavailable"}

    G = _build_column_graph(client)
    if G.number_of_nodes() == 0:
        return {"status": "skipped", "reason": "No nodes in graph"}

    components = list(nx.weakly_connected_components(G)) if G.is_directed() else list(nx.connected_components(G))
    node_to_wid: dict[str, int] = {}
    for wid, comp in enumerate(components):
        for node in comp:
            node_to_wid[node] = wid

    client.execute("BEGIN TRANSACTION")
    for fqn, wid in node_to_wid.items():
        client.execute(
            f"MATCH (c:Field {{fqn: $fqn}}) SET c.wcc_id = $wid",
            {"fqn": fqn, "wid": wid},
        )
    client.execute("COMMIT")
    logger.info("WCC completed: %d components", len(components))
    return {
        "status": "ok",
        "algo": "wcc",
        "result": {
            "componentCount": len(components),
            "nodePropertiesWritten": len(node_to_wid),
        },
    }
