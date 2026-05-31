"""In-memory MockNeo4jClient for local development.

Stores nodes and relationships in memory using Python dicts.
Supports the Cypher patterns used across this project:
  - UNWIND ... MERGE ... SET ...
  - MATCH ... WHERE ... RETURN ...
  - MATCH ... RETURN count(*) AS ...
  - MATCH ...-[r]->... RETURN count(*) AS ...
  - MATCH path = shortestPath(...)
  - CALL gds.graph.project.cypher(...)
  - CALL gds.{pagerank,louvain,betweenness,degree,nodeSimilarity,wcc}.write(...)
  - CALL db.schema.nodeTypeProperties()
  - CALL apoc.create.relationship(...)

Set A20_NEO4J_MOCK=1 to enable.
"""

from __future__ import annotations

import logging
import re
from threading import Lock
from typing import Any

logger = logging.getLogger(__name__)

_mock_lock = Lock()
_mock_instance: MockNeo4jClient | None = None


class _Node:
    __slots__ = ("labels", "props")

    def __init__(self, labels: set[str], props: dict[str, Any]) -> None:
        self.labels = labels
        self.props = props

    def __repr__(self) -> str:
        label = next(iter(self.labels)) if self.labels else ""
        return f"({label} {self.props})"


class _Relationship:
    __slots__ = ("src_fqn", "type_", "dst_fqn", "props")

    def __init__(self, src_fqn: str, type_: str, dst_fqn: str, props: dict[str, Any]) -> None:
        self.src_fqn = src_fqn
        self.type_ = type_
        self.dst_fqn = dst_fqn
        self.props = props


def _label_from_pattern(query: str) -> str | None:
    m = re.search(r"\((?:\w+)?:(\w+)", query)
    return m.group(1) if m else None


def _identity(val: Any) -> Any:
    return val


class MockNeo4jClient:
    def __init__(self) -> None:
        self._nodes: dict[str, _Node] = {}
        self._rels: list[_Relationship] = []
        self._next_id: int = 1

    # ── public API (matches Neo4jClient) ──────────────────────────────

    async def execute_schema(self, query: str, parameters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return self._execute(query, parameters or {})

    async def execute_data(self, query: str, parameters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return self._execute(query, parameters or {})

    async def close(self) -> None:
        self._nodes.clear()
        self._rels.clear()

    # ── dispatch ──────────────────────────────────────────────────────

    def _execute(self, query: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        query_stripped = query.strip()

        if query_stripped.startswith("UNWIND"):
            return self._handle_unwind_merge(query_stripped, params)
        if query_stripped.startswith("CALL gds.graph.project.cypher"):
            return self._handle_gds_project(query_stripped, params)
        if query_stripped.startswith("CALL gds."):
            return self._handle_gds_write(query_stripped, params)
        if query_stripped.startswith("CALL db.schema.nodeTypeProperties"):
            return self._handle_schema_props(query_stripped)
        if query_stripped.startswith("CALL apoc.create.relationship"):
            return self._handle_apoc_relationship(query_stripped, params)
        if "shortestPath" in query_stripped or "shortestPath" in query_stripped:
            return self._handle_shortest_path(query_stripped, params)
        if "UNWIND" in query_stripped and "MERGE" in query_stripped:
            return self._handle_unwind_merge(query_stripped, params)

        return self._handle_match(query_stripped, params)

    # ── handlers ──────────────────────────────────────────────────────

    def _match_nodes(
        self, labels: set[str] | None, conditions: dict[str, Any] | None = None, extra_conditions: str | None = None
    ) -> list[tuple[str, _Node]]:
        results: list[tuple[str, _Node]] = []
        for fqn, node in self._nodes.items():
            if labels and not labels.intersection(node.labels):
                continue
            if conditions:
                matched = True
                for k, v in conditions.items():
                    if node.props.get(k) != v:
                        matched = False
                        break
                if not matched:
                    continue
            if extra_conditions:
                if not self._eval_condition(node, extra_conditions):
                    continue
            results.append((fqn, node))
        return results

    def _eval_condition(self, node: _Node, condition: str, params: dict[str, Any] | None = None) -> bool:
        cond = condition.strip()
        if not cond:
            return True

        params = params or {}
        for k, v in params.items():
            if isinstance(v, str):
                cond = cond.replace(f"${k}", f"'{v}'")
            elif isinstance(v, (int, float)):
                cond = cond.replace(f"${k}", str(v))

        parts = re.split(r"\s+AND\s+", cond, flags=re.IGNORECASE)
        for part in parts:
            part = part.strip().strip("()")
            if not part:
                continue

            scalar_in = re.match(
                r"""['"]([^'"]+)['"]\s+IN\s+(?:\w+\.)?(\w+)""", part, re.IGNORECASE
            )
            if scalar_in:
                needle = scalar_in.group(1)
                prop = scalar_in.group(2)
                val = node.props.get(prop)
                if isinstance(val, list):
                    if needle not in val:
                        return False
                elif val != needle:
                    return False
                continue

            list_in = re.match(r"(?:\w+\.)?(\w+)\s+IN\s*\[(.+?)\]", part, re.IGNORECASE)
            if list_in:
                prop = list_in.group(1)
                vals_str = list_in.group(2)
                vals = [v.strip().strip("'\"") for v in vals_str.split(",")]
                val = node.props.get(prop)
                if isinstance(val, list):
                    if not any(v in val for v in vals):
                        return False
                else:
                    if val not in vals:
                        return False
                continue

            m = re.match(
                r"(?:\w+\.)?(\w+)\s*(CONTAINS|>=|<=|!=|<>|=|>|<|IS NULL|IS NOT NULL)\s*(.*)",
                part, re.IGNORECASE,
            )
            if not m:
                continue

            prop, op, raw = m.group(1), m.group(2).upper(), m.group(3).strip()
            val = node.props.get(prop)

            if op == "IS NULL":
                if val is not None:
                    return False
                continue
            if op == "IS NOT NULL":
                if val is None:
                    return False
                continue

            if raw.upper() == "NULL":
                rhs = None
            elif raw.upper() == "TRUE":
                rhs = True
            elif raw.upper() == "FALSE":
                rhs = False
            else:
                raw_clean = raw.strip("'\"")
                try:
                    rhs = int(raw_clean)
                except ValueError:
                    try:
                        rhs = float(raw_clean)
                    except ValueError:
                        rhs = raw_clean

            if op == "CONTAINS":
                if not (isinstance(val, str) and isinstance(rhs, str) and rhs in val):
                    return False
            elif op == ">=" and not (val is not None and val >= rhs):
                return False
            elif op == "<=" and not (val is not None and val <= rhs):
                return False
            elif op == ">" and not (val is not None and val > rhs):
                return False
            elif op == "<" and not (val is not None and val < rhs):
                return False
            elif op in ("!=", "<>") and val != rhs:
                return False
            elif op == "=" and val != rhs:
                return False
        return True

    def _parse_match(
        self, query: str, params: dict[str, Any]
    ) -> tuple[list[list[dict[str, Any]]], list[str], str | None]:
        lines = re.split(r"\s+WHERE\s+", query, flags=re.IGNORECASE, maxsplit=1)
        match_part = lines[0]
        raw_where = lines[1] if len(lines) > 1 else None
        if raw_where:
            where_part = re.split(
                r"\s+(RETURN|ORDER\s+BY|LIMIT|SKIP|WITH)\s+", raw_where,
                flags=re.IGNORECASE, maxsplit=1,
            )[0]
        else:
            where_part = None

        agg = re.search(r"RETURN\s+(count\(\*\)|count\(DISTINCT\s+\w+\)|collect\(.+?\)|.+?)(?:\s+AS\s+\w+)?", query, re.IGNORECASE)
        has_aggregation = bool(agg and ("count(" in agg.group(1).lower() or "collect(" in agg.group(1).lower()))

        return_clause = ""
        if "RETURN" in query.upper():
            return_match = re.search(r"RETURN\s+(.+?)(?:\s+ORDER\s+BY|\s+LIMIT|\s+SKIP|$)", query, re.IGNORECASE)
            if return_match:
                return_clause = return_match.group(1).strip()

        bindings: list[list[dict[str, Any]]] = []
        var = None

        table_label = _label_from_pattern(query) or "Table"

        if "()-[r]->()" in query or "()-[r]-()" in query:
            count_all = True
        else:
            count_all = False

        if count_all:
            return [], ["rel_count"], where_part

        labels = [table_label]

        m = re.findall(r"\((\w+):(\w+)", query)
        if m:
            labels = [lb for _, lb in m]

        if "OPTIONAL MATCH" in query.upper():
            pass

        simple_match = re.search(r"\((\w+):(\w+)(?:\s*\{([^}]+)\})?\)", query)
        if simple_match:
            var = simple_match.group(1)
            label = simple_match.group(2)
            props_str = simple_match.group(3)
            conditions: dict[str, Any] = {}
            if props_str:
                for pair in props_str.split(","):
                    pair = pair.strip()
                    if ":" in pair:
                        k, v = pair.split(":", 1)
                        k = k.strip()
                        v = v.strip().strip("'\"")
                        if v.startswith("$"):
                            v = params.get(v[1:], v)
                        conditions[k] = v

            matched = self._match_nodes({label}, conditions)
            if matched:
                for fqn, node in matched:
                    bindings.append([{var: node.props}])
                return bindings, ["n"], where_part

        return [], [c.strip().split()[-1] for c in return_clause.split(",") if c.strip()], where_part

    def _parse_return_clause(self, query: str) -> tuple[str, list[tuple[str, str]]]:
        m = re.search(r"RETURN\s+(.+?)(?:\s+ORDER\s+BY|\s+LIMIT|\s+SKIP|$)", query, re.IGNORECASE)
        clause = m.group(1).strip() if m else ""
        cols: list[tuple[str, str]] = []
        if clause:
            raw = re.split(r",\s*(?![^()]*\))", clause)
            for col in raw:
                col = col.strip()
                if not col:
                    continue
                if col == "*":
                    cols.append(("*", "*", "prop"))
                    continue
                clm = re.search(r"collect\((.+?)\)(?:\s*\[.*?\])?\s*AS\s+(\w+)", col, re.IGNORECASE)
                if clm:
                    cols.append(("collect", clm.group(2), "collect"))
                    continue
                cm = re.search(r"count\(\*\)\s*AS\s*(\w+)", col, re.IGNORECASE)
                if cm:
                    cols.append(("count(*)", cm.group(1), "count"))
                    continue
                cs = re.search(r"count\(\*\)", col, re.IGNORECASE)
                if cs:
                    cols.append(("count(*)", "count(*)", "count"))
                    continue
                am = re.search(r"(?:\w+\.)?(\w+)\s+AS\s+(\w+)", col, re.IGNORECASE)
                if am:
                    cols.append((am.group(1), am.group(2), "prop"))
                    continue
                sm = re.search(r"(?:\w+\.)?(\w+)", col)
                if sm:
                    cols.append((sm.group(1), sm.group(1), "prop"))
        return clause, cols

    def _handle_match(self, query: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        bindings, columns, where_part = self._parse_match(query, params)
        _, return_cols = self._parse_return_clause(query)

        is_relation_count = "()-[r]->()" in query or "()-[r]-()" in query
        has_aggregation = any(c[2] in ("count", "collect") for c in return_cols)

        labels = _label_from_pattern(query)
        label_set = {labels} if labels else None

        if has_aggregation:
            if is_relation_count:
                matched = [(None, None) for _ in range(len(self._rels))]
            else:
                matched = self._match_nodes(label_set)
                if where_part:
                    matched = [(f, n) for f, n in matched if self._eval_condition(n, where_part, params)]

            row: dict[str, Any] = {}
            for prop, alias, col_type in return_cols:
                if col_type == "count":
                    row[alias] = len(matched)
                elif col_type == "collect":
                    row[alias] = [n.props.get("name", "") for _, n in matched][:10] if matched else []
                else:
                    row[alias] = matched[0][1].props.get(prop, 0) if matched else 0
            return [row] if matched else []

        if where_part:
            filtered = []
            for bg in bindings:
                for entry in bg:
                    for var_name, props in entry.items():
                        node = _Node(labels=label_set or set(), props=props if isinstance(props, dict) else {})
                        if self._eval_condition(node, where_part, params):
                            filtered.append(bg)
                        break
            bindings = filtered

        if not bindings:
            alias = return_cols[0][1] if return_cols else None
            return [{alias: 0}] if alias and any(c[2] == "count" for c in return_cols) else []

        return self._build_results(query, bindings, columns, where_part)

    def _build_results(
        self,
        query: str,
        bindings: list[list[dict[str, Any]]],
        columns: list[str],
        where_part: str | None,
    ) -> list[dict[str, Any]]:
        if not bindings and not columns:
            return []

        if not columns:
            return [{k: v for b in bindings for k, v in b[0].items()}][:1] if bindings else []

        limit = None
        limit_m = re.search(r"LIMIT\s+(\d+)", query, re.IGNORECASE)
        if limit_m:
            limit = int(limit_m.group(1))

        order_col = None
        order_dir = None
        order_m = re.search(r"ORDER\s+BY\s+(?:\w+\.)?(\w+)\s*(DESC|ASC)?", query, re.IGNORECASE)
        if order_m:
            order_col = order_m.group(1)
            order_dir = (order_m.group(2) or "ASC").upper()

        _, raw_cols = self._parse_return_clause(query)
        col_map = [(c[0], c[1]) for c in raw_cols]  # (prop, alias)
        if not col_map:
            for col in columns:
                col = col.strip()
                if not col:
                    continue
                if col == "*":
                    col_map.append(("*", "*"))
                    continue
                am = re.search(r"(?:\w+\.)?(\w+)\s+AS\s+(\w+)", col, re.IGNORECASE)
                if am:
                    col_map.append((am.group(1), am.group(2)))
                    continue
                sm = re.search(r"(?:\w+\.)?(\w+)", col)
                if sm:
                    col_map.append((sm.group(1), sm.group(1)))

        if not col_map:
            return []

        rows: list[dict[str, Any]] = []
        for binding_group in bindings:
            row: dict[str, Any] = {}
            for var_name, var_data in binding_group[0].items() if binding_group else [("", {})]:
                _ = var_name
                for prop, alias in col_map:
                    if prop == "*":
                        if isinstance(var_data, dict):
                            row.update(var_data)
                    else:
                        val = var_data.get(prop) if isinstance(var_data, dict) else None
                        row[alias] = val if val is not None else 0

            if row:
                rows.append(row)

        if not rows:
            cols_final: dict[str, Any] = {}
            for _, alias in col_map:
                if alias == "*":
                    continue
                cols_final[alias] = 0
            if cols_final:
                rows = [cols_final]

        if order_col:
            try:
                rows.sort(
                    key=lambda r: (r.get(order_col) is not None, r.get(order_col, 0) or 0) if order_col else 0,
                    reverse=(order_dir == "DESC"),
                )
            except Exception:
                pass

        if limit:
            rows = rows[:limit]

        return rows

    def _handle_unwind_merge(self, query: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        batch = params.get("batch", [])
        if not batch:
            return []

        if "CALL apoc.create.relationship" in query:
            return self._handle_apoc_relationship(query, params)

        label_m = re.search(r"MERGE\s+\(\w+:(\w+)", query)
        label = label_m.group(1) if label_m else "Node"

        key_m = re.search(r"\{\s*(\w+):\s*(?:\w+\.)?(\w+)\s*\}", query)
        key_field = key_m.group(1) if key_m else None

        has_rel = bool(re.search(r"MERGE\s+\((\w+)\)\s*-\[:(\w+)\]\s*->\s*\((\w+)\)", query))
        has_nested_unwind = "UNWIND row.domains" in query or "UNWIND" in query.split("WITH")[-1] if "WITH" in query else False

        for item in batch:
            if not isinstance(item, dict):
                continue

            if key_field and key_field in item:
                fqn = str(item[key_field])
            elif item.get("fqn"):
                fqn = str(item["fqn"])
            elif item.get("code"):
                fqn = str(item["code"])
            else:
                fqn = f"node_{self._next_id}"

            existing = self._nodes.get(fqn)
            if existing:
                for k, v in item.items():
                    existing.props[k] = v
                existing.labels.add(label)
            else:
                new_node = _Node(labels={label}, props=dict(item))
                self._nodes[fqn] = new_node
                self._next_id += 1

            rels_created = set()

            if has_rel:
                rel_m = re.search(r"MERGE\s+\((\w+)\)\s*-\[:(\w+)\]\s*->\s*\((\w+)\)", query)
                if rel_m:
                    src_var = rel_m.group(1)
                    rel_type = rel_m.group(2)
                    dst_var = rel_m.group(3)

                    if rel_type == "HAS_COLUMN":
                        table_fqn = item.get("table_fqn", "")
                        if table_fqn and self._nodes.get(table_fqn):
                            self._rels.append(
                                _Relationship(table_fqn, "HAS_COLUMN", fqn, {})
                            )
                            rels_created.add((table_fqn, "HAS_COLUMN", fqn))

                if has_nested_unwind:
                    domains = item.get("domains", [])
                    if isinstance(domains, list):
                        for dc in domains:
                            dst_node = self._nodes.get(dc)
                            if dst_node:
                                key = (fqn, "IN_DOMAIN", dc)
                                if key not in rels_created:
                                    self._rels.append(
                                        _Relationship(fqn, "IN_DOMAIN", dc, {"source": "registry"})
                                    )
                                    rels_created.add(key)

            if "MATCH (t:Table {fqn: row.table_fqn})" in query or "MATCH (t:Table " in query:
                table_fqn = item.get("table_fqn", "")
                table_node = self._nodes.get(table_fqn)
                col_node = self._nodes.get(fqn)
                if table_node and col_node:
                    key = (table_fqn, "HAS_COLUMN", fqn)
                    if key not in rels_created:
                        self._rels.append(
                            _Relationship(table_fqn, "HAS_COLUMN", fqn, {})
                        )

        return [{"count(*)": len(batch)}]

    def _handle_apoc_relationship(self, query: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        batch = params.get("batch", [])
        if not batch:
            return [{"count(*)": 0}]

        for item in batch:
            src_fqn = item.get("src_fqn", "")
            dst_fqn = item.get("dst_fqn", "")
            rel_type = item.get("rel_type", "")
            props = item.get("props", {})
            status = item.get("status", "")
            source = item.get("source", "")

            src_node = self._nodes.get(src_fqn)
            dst_node = self._nodes.get(dst_fqn)

            if src_node and dst_node:
                rel_props = dict(props)
                if source:
                    rel_props["source"] = source
                if status:
                    rel_props["status"] = status
                self._rels.append(
                    _Relationship(src_fqn, rel_type, dst_fqn, rel_props)
                )

        return [{"count(*)": len(batch)}]

    def _handle_gds_project(self, query: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {
                "graphName": "mock_graph",
                "nodeCount": len(self._nodes),
                "relationshipCount": len(self._rels),
            }
        ]

    def _handle_gds_write(self, query: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        match_count = self._next_id - 1
        result = {
            "nodePropertiesWritten": match_count,
            "relationshipsWritten": len(self._rels),
            "ranIterations": 20,
            "communityCount": 3,
            "modularity": 0.45,
            "ranLevels": 4,
            "componentCount": 2,
            "nodesCompared": match_count,
            "similarityDistribution": {
                "min": 0.1,
                "max": 0.95,
                "mean": 0.5,
                "stdDev": 0.2,
                "p1": 0.1,
                "p5": 0.2,
                "p10": 0.25,
                "p25": 0.35,
                "p50": 0.5,
                "p75": 0.65,
                "p90": 0.8,
                "p95": 0.85,
                "p99": 0.92,
            },
        }

        if "pagerank" in query.lower():
            for fqn, node in self._nodes.items():
                node.props["pagerank"] = 0.1
        elif "betweenness" in query.lower():
            for fqn, node in self._nodes.items():
                node.props["betweenness"] = 0.05
        elif "degree" in query.lower():
            for fqn, node in self._nodes.items():
                node.props["degree"] = 3
        elif "louvain" in query.lower() or "community" in query.lower():
            for fqn, node in self._nodes.items():
                node.props["community_id"] = 1
                node.props["wcc_id"] = 0
        elif "nodeSimilarity" in query.lower():
            result["relationshipsWritten"] = 5

        return [result]

    def _handle_schema_props(self, query: str) -> list[dict[str, Any]]:
        node_types = set()
        for fqn, node in self._nodes.items():
            for label in node.labels:
                node_types.add(label)

        results = []
        for label in node_types:
            props_map: dict[str, set[str]] = {}
            for fqn, node in self._nodes.items():
                if label in node.labels:
                    for k, v in node.props.items():
                        if k not in props_map:
                            props_map[k] = set()
                        props_map[k].add(type(v).__name__ if v is not None else "Null")

            for prop_name, types in props_map.items():
                results.append(
                    {
                        "nodeType": label,
                        "propertyName": prop_name,
                        "propertyTypes": list(types),
                    }
                )

        if not results:
            results.append(
                {
                    "nodeType": "Table",
                    "propertyName": "fqn",
                    "propertyTypes": ["String"],
                }
            )

        return results

    def _handle_shortest_path(self, query: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        src_fqn = params.get("a_fqn") or params.get("fqn", "")
        dst_fqn = params.get("b_fqn", "")
        max_depth = params.get("max_depth") or params.get("max_hops", 5)

        src_node = self._nodes.get(src_fqn)
        dst_node = self._nodes.get(dst_fqn)

        if not src_node or not dst_node or src_fqn == dst_fqn:
            return []

        visited = {src_fqn}
        queue = [(src_fqn, [src_fqn], [])]
        while queue:
            current, node_path, rel_path = queue.pop(0)
            if current == dst_fqn:
                return [
                    {
                        "node_path": [f"Table:{fp}" if fp in self._nodes and "Table" in self._nodes[fp].labels else f"Column:{fp}" for fp in node_path],
                        "rel_path": rel_path,
                        "hops": len(node_path) - 1,
                    }
                ]
            if len(node_path) > max_depth:
                continue

            for rel in self._rels:
                if rel.src_fqn == current and rel.dst_fqn not in visited:
                    visited.add(rel.dst_fqn)
                    queue.append(
                        (rel.dst_fqn, node_path + [rel.dst_fqn], rel_path + [rel.type_])
                    )
                if rel.dst_fqn == current and rel.src_fqn not in visited:
                    visited.add(rel.src_fqn)
                    queue.append(
                        (rel.src_fqn, node_path + [rel.src_fqn], rel_path + [rel.type_])
                    )

        return []


def get_mock_client() -> MockNeo4jClient:
    global _mock_instance
    if _mock_instance is None:
        with _mock_lock:
            if _mock_instance is None:
                _mock_instance = MockNeo4jClient()
                logger.info("[MockNeo4jClient] Using in-memory mock client")
    return _mock_instance


def close_mock_client() -> None:
    global _mock_instance
    with _mock_lock:
        if _mock_instance:
            _mock_instance._nodes.clear()
            _mock_instance._rels.clear()
            _mock_instance = None
            logger.info("[MockNeo4jClient] Mock client closed")
