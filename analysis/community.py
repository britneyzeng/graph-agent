"""GDS community detection — Louvain multi-resolution, WCC."""

from __future__ import annotations

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


def run_louvain(
    domain: str | None = None,
    resolution: float = 1.0,
    write_property: str = "community_id",
    **kwargs,
) -> dict[str, Any]:
    client = _get_client()
    if client is None:
        return {"status": "skipped", "reason": "Neo4j client unavailable"}

    graph_name = "proc_louvain"

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
            CALL gds.louvain.write('{graph_name}', {{
                writeProperty: '{write_property}',
                includeIntermediateCommunities: true,
                maxLevels: 10,
                resolution: {resolution}
            }})
            YIELD communityCount, modularity, ranLevels, nodePropertiesWritten
            RETURN communityCount, modularity, ranLevels, nodePropertiesWritten
            """
        )
        result = dict(rows[0]) if rows else {}
        logger.info("Louvain completed: %s", result)
        return {"status": "ok", "algo": "louvain", "result": result}
    except Exception as e:
        logger.error("Louvain write failed: %s", e)
        return {"status": "error", "error": str(e)}


def run_wcc(domain: str | None = None, **kwargs) -> dict[str, Any]:
    client = _get_client()
    if client is None:
        return {"status": "skipped", "reason": "Neo4j client unavailable"}

    graph_name = "proc_wcc"

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
            CALL gds.wcc.write('{graph_name}', {{
                writeProperty: 'wcc_id'
            }})
            YIELD nodePropertiesWritten, componentCount
            RETURN nodePropertiesWritten, componentCount
            """
        )
        result = dict(rows[0]) if rows else {}
        logger.info("WCC completed: %s", result)
        return {"status": "ok", "algo": "wcc", "result": result}
    except Exception as e:
        logger.error("WCC write failed: %s", e)
        return {"status": "error", "error": str(e)}
