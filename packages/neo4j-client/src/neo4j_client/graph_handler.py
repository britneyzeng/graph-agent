"""Graph handler for building queries and transforming results for Neo4j.

This module provides utility functions for converting Neo4j query results
into a graph structure format similar to KGraphClient output.
"""

from __future__ import annotations

from typing import Any


def transform_paths_to_graph(path_list: list[Any]) -> dict[str, Any]:
    """Transform path results into a graph structure.

    Converts Neo4j path results into a format similar to Kuzu/KGraph output,
    with nodes and relationships lists.

    Neo4j driver's record.data() serializes Path objects as a list where:
    - Even indices (0, 2, 4, ...) are nodes
    - Odd indices (1, 3, 5, ...) are relationships

    Args:
        path_list: List of path objects from Neo4j query results

    Returns:
        Dictionary with nodes and relationships lists
    """
    graph: dict[str, Any] = {"nodes": [], "rels": []}

    seen_nodes: dict[str, bool] = {}
    seen_rels: set[str] = set()

    for path in path_list:
        current_path_nodes: list[Any] = []
        current_path_rels: list[Any] = []

        # Neo4j driver serializes Path as alternating nodes and relationships
        if isinstance(path, list):
            for i, item in enumerate(path):
                if i % 2 == 0:
                    # Even index: node
                    current_path_nodes.append(_neo4j_node_to_dict(item))
                else:
                    # Odd index: relationship
                    current_path_rels.append(_neo4j_rel_to_dict(item))

        for node in current_path_nodes:
            node_id = str(node.get("_id") or node.get("id", ""))
            node_label = _get_node_label(node)

            if node_id not in seen_nodes:
                # Extract properties
                if "properties" in node:
                    properties = node.get("properties", {})
                else:
                    properties = {
                        k: v
                        for k, v in node.items()
                        if k not in ["_id", "_label", "id", "labels", "name"]
                    }

                node_data = {
                    "_id": node_id,
                    "name": node.get("name") or node_id,
                    "entity_type": node_label,
                    "properties": properties,
                }

                seen_nodes[node_id] = True
                graph["nodes"].append(node_data)

        for rel in current_path_rels:
            # Get relationship ID
            rel_id = str(rel.get("_id") or rel.get("id", ""))
            rel_key = rel_id

            if rel_key in seen_rels:
                continue

            # Get source and target IDs
            src_id = str(rel.get("_src") or rel.get("start_node", "") or rel.get("source", ""))
            dst_id = str(rel.get("_dst") or rel.get("end_node", "") or rel.get("target", ""))
            rel_type = rel.get("_label") or rel.get("type", "")

            graph["rels"].append(
                {
                    "source": src_id,
                    "target": dst_id,
                    "rel_type": rel_type,
                }
            )

            seen_rels.add(rel_key)

    return {"graph": graph}


def _get_node_label(node: dict[str, Any]) -> str:
    """Get node label from various formats.

    Args:
        node: Node dictionary

    Returns:
        Node label string
    """
    labels = node.get("_label")
    if labels:
        return labels

    labels = node.get("labels")
    if isinstance(labels, list):
        return labels[0] if labels else ""
    return labels or ""


def _neo4j_node_to_dict(node: Any) -> dict[str, Any]:
    """Convert Neo4j node object to dictionary.

    Args:
        node: Neo4j Node object or dict

    Returns:
        Node as dictionary
    """
    if isinstance(node, dict):
        return node

    try:
        node_id = node.element_id if hasattr(node, "element_id") else node.id
        labels = list(node.labels) if hasattr(node, "labels") else []

        return {
            "_id": node_id,
            "_label": labels[0] if labels else "",
            "labels": labels,
            "name": node.get("name", ""),
            "properties": dict(node),
        }
    except Exception:
        return {"_id": "", "_label": "", "properties": {}}


def _neo4j_rel_to_dict(rel: Any) -> dict[str, Any]:
    """Convert Neo4j relationship object to dictionary.

    Args:
        rel: Neo4j Relationship object or dict

    Returns:
        Relationship as dictionary
    """
    if isinstance(rel, dict):
        return rel

    try:
        rel_id = rel.element_id if hasattr(rel, "element_id") else rel.id
        start_node = rel.start_node if hasattr(rel, "start_node") else None
        end_node = rel.end_node if hasattr(rel, "end_node") else None

        start_id = (
            start_node.element_id
            if start_node and hasattr(start_node, "element_id")
            else start_node.id
            if start_node
            else ""
        )
        end_id = (
            end_node.element_id
            if end_node and hasattr(end_node, "element_id")
            else end_node.id
            if end_node
            else ""
        )

        return {
            "_id": rel_id,
            "_label": rel.type if hasattr(rel, "type") else "",
            "_src": start_id,
            "_dst": end_id,
            "properties": dict(rel),
        }
    except Exception:
        return {"_id": "", "_label": "", "_src": "", "_dst": ""}
