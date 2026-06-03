from __future__ import annotations

import logging
from typing import Any

import networkx as nx

from analysis import build_graph, get_client

logger = logging.getLogger(__name__)


def run_louvain_field(
    domain: str | None = None,
    resolution: float = 1.0,
    write_property: str = "community_id",
    **kwargs,
) -> dict[str, Any]:
    client = get_client()
    if client is None:
        return {"status": "skipped", "reason": "Kuzu client unavailable"}

    G = build_graph(client, "Field", "FIELD_LINK")
    if G.number_of_nodes() == 0:
        return {"status": "skipped", "reason": "No nodes in graph"}

    communities = nx.community.louvain_communities(G, resolution=resolution, seed=42)
    node_to_cid: dict[str, int] = {}
    for cid, comm in enumerate(communities):
        for node in comm:
            node_to_cid[node] = cid

    for fqn, cid in node_to_cid.items():
        client.execute(
            f"MATCH (c:Field {{fqn: $fqn}}) SET c.{write_property} = $cid",
            {"fqn": fqn, "cid": cid},
        )
    logger.info("Field Louvain completed: %d communities", len(communities))
    return {
        "status": "ok",
        "algo": "louvain_field",
        "result": {
            "communityCount": len(communities),
            "modularity": 0.0,
            "ranLevels": 0,
            "nodePropertiesWritten": len(node_to_cid),
        },
    }


def run_louvain_entity(
    domain: str | None = None,
    resolution: float = 1.0,
    write_property: str = "community_id",
    **kwargs,
) -> dict[str, Any]:
    client = get_client()
    if client is None:
        return {"status": "skipped", "reason": "Kuzu client unavailable"}

    G = build_graph(client, "Entity", "ENTITY_LINK")
    if G.number_of_nodes() == 0:
        return {"status": "skipped", "reason": "No nodes in graph"}

    communities = nx.community.louvain_communities(G, resolution=resolution, seed=42)
    node_to_cid: dict[str, int] = {}
    for cid, comm in enumerate(communities):
        for node in comm:
            node_to_cid[node] = cid

    for fqn, cid in node_to_cid.items():
        client.execute(
            f"MATCH (e:Entity {{fqn: $fqn}}) SET e.{write_property} = $cid",
            {"fqn": fqn, "cid": cid},
        )
    logger.info("Entity Louvain completed: %d communities", len(communities))
    return {
        "status": "ok",
        "algo": "louvain_entity",
        "result": {
            "communityCount": len(communities),
            "modularity": 0.0,
            "ranLevels": 0,
            "nodePropertiesWritten": len(node_to_cid),
        },
    }
