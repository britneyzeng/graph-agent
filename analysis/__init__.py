from __future__ import annotations

import logging
from typing import Any

import networkx as nx

try:
    from kuzu_client import get_kuzu_client
except ImportError:
    get_kuzu_client = None

logger = logging.getLogger(__name__)


def get_client() -> Any:
    try:
        return get_kuzu_client()
    except Exception as e:
        logger.warning("Kuzu client not available: %s", e)
        return None


def build_graph(client, label: str, rel_type: str, graph_name: str = "") -> nx.Graph:
    G = nx.Graph()
    rows = client.execute(f"MATCH (n:{label}) RETURN n.fqn AS fqn")
    for r in rows:
        G.add_node(r["fqn"])
    rows = client.execute(
        f"MATCH (n1:{label})-[r:{rel_type}]-(n2:{label}) "
        "RETURN n1.fqn AS src, n2.fqn AS dst"
    )
    for r in rows:
        G.add_edge(r["src"], r["dst"])
    if graph_name:
        logger.info("Built %s graph with %d nodes, %d edges", graph_name, G.number_of_nodes(), G.number_of_edges())
    return G


__all__ = ["get_client", "build_graph"]
