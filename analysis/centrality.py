"""GDS centrality analysis — PageRank, Betweenness, Degree."""

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


def run_pagerank(domain: str | None = None, write_property: str = "pagerank", **kwargs) -> dict[str, Any]:
    """Project Column graph and run PageRank, writing pagerank scores back."""
    client = _get_client()
    if client is None:
        return {"status": "skipped", "reason": "Neo4j client unavailable"}

    graph_name = "proc_pagerank"

    node_filter = "Column"
    rel_filter = "REFERENCES|JOINS_WITH"

    cypher = f"""
        CALL gds.graph.project.cypher(
            '{graph_name}',
            'MATCH (c:Column) RETURN id(c) AS id',
            'MATCH (c1:Column)-[r:{rel_filter}]-(c2:Column) RETURN id(c1) AS source, id(c2) AS target'
        )
        YIELD graphName, nodeCount, relationshipCount
        RETURN graphName, nodeCount, relationshipCount
    """
    try:
        client.execute_schema(cypher)
    except Exception as e:
        if "already exists" in str(e):
            pass
        else:
            logger.error("Graph project failed: %s", e)

    try:
        rows = client.execute_schema(
            f"""
            CALL gds.pageRank.write('{graph_name}', {{
                writeProperty: '{write_property}',
                maxIterations: 20,
                dampingFactor: 0.85
            }})
            YIELD nodePropertiesWritten, ranIterations
            RETURN nodePropertiesWritten, ranIterations
            """
        )
        result = dict(rows[0]) if rows else {}
        logger.info("PageRank completed: %s", result)
        return {"status": "ok", "algo": "pagerank", "result": result}
    except Exception as e:
        logger.error("PageRank write failed: %s", e)
        return {"status": "error", "error": str(e)}


def run_betweenness(domain: str | None = None, write_property: str = "betweenness", **kwargs) -> dict[str, Any]:
    client = _get_client()
    if client is None:
        return {"status": "skipped", "reason": "Neo4j client unavailable"}

    graph_name = "proc_betweenness"

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
            CALL gds.betweenness.write('{graph_name}', {{
                writeProperty: '{write_property}'
            }})
            YIELD nodePropertiesWritten
            RETURN nodePropertiesWritten
            """
        )
        result = dict(rows[0]) if rows else {}
        logger.info("Betweenness completed: %s", result)
        return {"status": "ok", "algo": "betweenness", "result": result}
    except Exception as e:
        logger.error("Betweenness write failed: %s", e)
        return {"status": "error", "error": str(e)}


def run_degree(domain: str | None = None, write_property: str = "degree", **kwargs) -> dict[str, Any]:
    client = _get_client()
    if client is None:
        return {"status": "skipped", "reason": "Neo4j client unavailable"}

    graph_name = "proc_degree"

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
            CALL gds.degree.write('{graph_name}', {{
                writeProperty: '{write_property}',
                orientation: 'UNDIRECTED'
            }})
            YIELD nodePropertiesWritten
            RETURN nodePropertiesWritten
            """
        )
        result = dict(rows[0]) if rows else {}
        logger.info("Degree completed: %s", result)
        return {"status": "ok", "algo": "degree", "result": result}
    except Exception as e:
        logger.error("Degree write failed: %s", e)
        return {"status": "error", "error": str(e)}
