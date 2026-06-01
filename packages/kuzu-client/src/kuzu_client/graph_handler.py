"""Graph transformation utilities for Kuzu query results.

Converts Kuzu path query results (variable-length match, etc.) into a
standard graph structure with nodes and relationships lists, compatible
with downstream tool output formatting.
"""

from __future__ import annotations

from typing import Any


def _node_id_str(node_id: Any) -> str:
    if isinstance(node_id, dict):
        return f"{node_id.get('table', 0)}:{node_id.get('offset', 0)}"
    return str(node_id)


def _kuzu_node_to_dict(node: dict[str, Any]) -> dict[str, Any]:
    label = node.get("_label", "")
    nid = _node_id_str(node.get("_id", ""))
    props = {k: v for k, v in node.items() if not k.startswith("_")}
    return {
        "_id": nid,
        "_label": label,
        "labels": [label] if label else [],
        "name": props.get("name", nid),
        "properties": props,
    }


def _kuzu_rel_to_dict(rel: dict[str, Any]) -> dict[str, Any]:
    return {
        "_id": _node_id_str(rel.get("_id", "")),
        "_label": rel.get("_label", ""),
        "_src": _node_id_str(rel.get("_src", "")),
        "_dst": _node_id_str(rel.get("_dst", "")),
        "properties": {k: v for k, v in rel.items() if not k.startswith("_")},
    }


def transform_path_to_graph(path: Any) -> dict[str, Any]:
    """Convert a single Kuzu path value to graph format.

    Args:
        path: Path dict as returned by Kuzu, with ``_nodes`` and ``_rels`` keys,
              or a list of alternating node/rel objects (Neo4j compat fallback).

    Returns:
        Graph dict with ``graph.nodes`` and ``graph.rels`` lists.
    """
    nodes: list[dict[str, Any]] = []
    rels: list[dict[str, Any]] = []
    seen_nodes: dict[str, bool] = {}
    seen_rels: set[str] = set()

    if isinstance(path, dict) and "_nodes" in path and "_rels" in path:
        raw_nodes: list[dict[str, Any]] = path["_nodes"]
        raw_rels: list[dict[str, Any]] = path["_rels"]

        for raw in raw_nodes:
            node = _kuzu_node_to_dict(raw)
            nid = str(node["_id"])
            if nid not in seen_nodes:
                seen_nodes[nid] = True
                nodes.append(node)

        for raw in raw_rels:
            rel = _kuzu_rel_to_dict(raw)
            rid = str(rel["_id"])
            if rid not in seen_rels:
                seen_rels.add(rid)
                rels.append(rel)

    elif isinstance(path, list):
        for i, item in enumerate(path):
            if i % 2 == 0:
                node = _kuzu_node_to_dict(item) if isinstance(item, dict) else {}
                nid = str(node.get("_id", ""))
                if nid and nid not in seen_nodes:
                    seen_nodes[nid] = True
                    nodes.append(node)
            else:
                rel = _kuzu_rel_to_dict(item) if isinstance(item, dict) else {}
                rid = str(rel.get("_id", ""))
                if rid and rid not in seen_rels:
                    seen_rels.add(rid)
                    rels.append(rel)

    return {"nodes": nodes, "rels": rels}


def results_to_graph(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Transform a list of result rows (from a path query) into a flat graph.

    Scans every column of every row for Kuzu path dicts (containing ``_nodes``)
    and merges all discovered nodes/rels into a single deduplicated graph.

    Args:
        results: Query results as returned by ``KuzuClient.execute()``.

    Returns:
        Graph dict with ``graph.nodes`` and ``graph.rels`` lists.
    """
    graph: dict[str, Any] = {"nodes": [], "rels": []}
    seen_nodes: dict[str, bool] = {}
    seen_rels: set[str] = set()

    for row in results:
        for col, val in row.items():
            if isinstance(val, dict) and "_nodes" in val:
                partial = transform_path_to_graph(val)
                for n in partial.get("nodes", []):
                    nid = str(n["_id"])
                    if nid not in seen_nodes:
                        seen_nodes[nid] = True
                        graph["nodes"].append(n)
                for r in partial.get("rels", []):
                    rid = str(r["_id"])
                    if rid not in seen_rels:
                        seen_rels.add(rid)
                        graph["rels"].append(r)

    return {"graph": graph}
