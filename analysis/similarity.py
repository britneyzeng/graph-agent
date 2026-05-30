"""GDS node similarity — Jaccard-based neighbor similarity."""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _get_client():
    try:
        from neo4j_client import get_neo4j_client

        return get_neo4j_client()
    except Exception as e:
        logger.warning("Neo4j client not available: %s", e)
        return None


def run_node_similarity(
    domain: str | None = None,
    top_k: int = 10,
    similarity_cutoff: float = 0.3,
    **kwargs,
) -> dict[str, Any]:
    """Run nodeSimilarity and write SIMILAR_TO relationships back to Neo4j."""
    client = _get_client()
    if client is None:
        return {"status": "skipped", "reason": "Neo4j client unavailable"}

    graph_name = "proc_similarity"

    try:
        client.execute_schema(
            f"""
            CALL gds.graph.project.cypher(
                '{graph_name}',
                'MATCH (c:Column) RETURN id(c) AS id',
                'MATCH (c1:Column)-[r:REFERENCES|JOINS_WITH]-(c2:Column) RETURN id(c1) AS source, id(c2) AS target'
            )
            YIELD graphName, nodeCount, relationshipCount
            RETURN graphName, nodeCount, relationshipCount
            """
        )
    except Exception:
        pass

    try:
        rows = client.execute_schema(
            f"""
            CALL gds.nodeSimilarity.write('{graph_name}', {{
                writeRelationshipType: 'SIMILAR_TO',
                writeProperty: 'score',
                topK: {top_k},
                similarityCutoff: {similarity_cutoff}
            }})
            YIELD nodesCompared, relationshipsWritten, similarityDistribution
            RETURN nodesCompared, relationshipsWritten, similarityDistribution
            """
        )
        result = dict(rows[0]) if rows else {}
        logger.info("nodeSimilarity completed: %s", result)
        return {"status": "ok", "algo": "nodeSimilarity", "result": result}
    except Exception as e:
        logger.error("nodeSimilarity write failed: %s", e)
        return {"status": "error", "error": str(e)}
