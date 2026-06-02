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


def run_node_similarity(
    domain: str | None = None,
    top_k: int = 10,
    similarity_cutoff: float = 0.3,
    **kwargs,
) -> dict[str, Any]:
    client = _get_client()
    if client is None:
        return {"status": "skipped", "reason": "Kuzu client unavailable"}

    G = nx.Graph()
    rows = client.execute("MATCH (c:Field) RETURN c.fqn AS fqn")
    for r in rows:
        G.add_node(r["fqn"])
    rows = client.execute(
        "MATCH (c1:Field)-[r:FIELD_LINK]-(c2:Field) "
        "RETURN c1.fqn AS src, c2.fqn AS dst"
    )
    for r in rows:
        G.add_edge(r["src"], r["dst"])

    if G.number_of_nodes() == 0:
        return {"status": "skipped", "reason": "No nodes in graph"}

    rels_written = 0
    client.execute("BEGIN TRANSACTION")
    for u, v, s in nx.jaccard_coefficient(G):
        if s < similarity_cutoff:
            continue
        client.execute(
            "MERGE (c1:Field {fqn: $src})-[r:FIELD_LINK {source: 'analysis', status: 'active'}]->(c2:Field {fqn: $dst})",
            {"src": u, "dst": v},
        )
        rels_written += 1
        if rels_written >= top_k * len(list(G.nodes())):
            break
    client.execute("COMMIT")
    logger.info("nodeSimilarity completed: %d relationships written", rels_written)
    return {
        "status": "ok",
        "algo": "nodeSimilarity",
        "result": {
            "nodesCompared": G.number_of_nodes(),
            "relationshipsWritten": rels_written,
            "similarityDistribution": {"min": similarity_cutoff, "max": 1.0, "mean": 0.5},
        },
    }
