"""sqlglot AST parser for stored procedure SQL files.

Extracts three types of evidence from PostgreSQL SQL:
  - JOIN relations  (src_col ↔ dst_col with frequency)
  - Field DERIVES_FROM lineage (INSERT/UPDATE → SELECT expr)
  - Table CO_USED_WITH co-occurrence (per-procedure table sets)
"""

import hashlib
import logging
import re
from pathlib import Path

import sqlglot
from sqlglot import exp

logger = logging.getLogger(__name__)

# ── Data structures ──────────────────────────────────────────────


class JoinEvidence:
    def __init__(self, src_col_fqn: str, dst_col_fqn: str, join_type: str, context_sql: str):
        self.src_col_fqn = src_col_fqn
        self.dst_col_fqn = dst_col_fqn
        self.join_type = join_type
        self.context_sql = context_sql

    def __repr__(self):
        return f"Join({self.src_col_fqn} {self.join_type} {self.dst_col_fqn})"


class LineageEvidence:
    def __init__(self, src_col_fqn: str, dst_col_fqn: str, transform: str, context_sql: str):
        self.src_col_fqn = src_col_fqn
        self.dst_col_fqn = dst_col_fqn
        self.transform = transform
        self.context_sql = context_sql

    def __repr__(self):
        return f"Lineage({self.dst_col_fqn} := {self.src_col_fqn})"


class CooccurrenceEvidence:
    def __init__(self, table_fqns: list[str]):
        self.table_fqns = sorted(table_fqns)

    def pairs(self):
        for i in range(len(self.table_fqns)):
            for j in range(i + 1, len(self.table_fqns)):
                yield (self.table_fqns[i], self.table_fqns[j])


class ParseResult:
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.file_hash: str = ""
        self.loc: int = 0
        self.parsed: bool = False
        self.error: str | None = None
        self.joins: list[JoinEvidence] = []
        self.lineages: list[LineageEvidence] = []
        self.cooccurrences: list[CooccurrenceEvidence] = []

    def merge(self, other: "ParseResult"):
        self.joins.extend(other.joins)
        self.lineages.extend(other.lineages)
        self.cooccurrences.extend(other.cooccurrences)


# ── Helper: scope resolution ─────────────────────────────────────


class Scope:
    """Tracks table aliases → physical names within a statement."""

    def __init__(self):
        self._aliases: dict[str, str] = {}

    def register(self, alias: str, physical: str):
        self._aliases[alias.lower()] = physical

    def resolve(self, name: str | None) -> str | None:
        if name is None:
            return None
        return self._aliases.get(name.lower(), name)

    def physical_name(self, table: exp.Table) -> str:
        alias = table.alias or table.name
        return self.resolve(alias) or table.name


# ── Main parser ──────────────────────────────────────────────────


class SqlParser:
    FQN_PATTERN = re.compile(r"^[\w.]+$")

    def __init__(self, schema_map: dict[str, str] | None = None):
        """schema_map: table_alias_or_name → fqn (e.g. po_order → proc.public.po_order)."""
        self.schema_map = schema_map or {}

    def parse_string(self, sql: str, file_name: str = "<string>") -> ParseResult:
        """Parse a SQL string directly (useful for tests and REPL)."""
        result = ParseResult(file_name)
        result.file_hash = hashlib.md5(sql.encode()).hexdigest()
        result.loc = sql.count("\n")

        try:
            statements = sqlglot.parse(sql, read="postgres")
        except Exception as e:
            result.error = f"Parse error: {e}"
            return result

        for stmt in statements:
            if stmt is None:
                continue
            self._walk_statement(stmt, result)

        result.parsed = True
        return result

    def parse_file(self, file_path: str | Path) -> ParseResult:
        path = Path(file_path)
        result = ParseResult(str(path))
        raw = path.read_text(encoding="utf-8", errors="replace")

        result.file_hash = hashlib.md5(raw.encode()).hexdigest()
        result.loc = raw.count("\n")

        try:
            statements = sqlglot.parse(raw, read="postgres")
        except Exception as e:
            result.error = f"Parse error: {e}"
            return result

        for stmt in statements:
            if stmt is None:
                continue
            self._walk_statement(stmt, result)

        result.parsed = True
        return result

    def _walk_statement(self, stmt: exp.Expression, result: ParseResult):
        if isinstance(stmt, exp.Select):
            scope = self._build_scope(stmt)
            self._extract_joins(stmt, scope, result)
            self._extract_cooccurrence(stmt, scope, result)

        elif isinstance(stmt, exp.Insert):
            scope = self._build_scope(stmt)
            self._extract_lineage_insert(stmt, scope, result)
            self._extract_joins(stmt, scope, result)
            self._extract_cooccurrence(stmt, scope, result)

        elif isinstance(stmt, exp.Update):
            scope = self._build_scope(stmt)
            self._extract_lineage_update(stmt, scope, result)
            self._extract_joins(stmt, scope, result)
            self._extract_cooccurrence(stmt, scope, result)

        elif isinstance(stmt, exp.Union):
            for s in stmt.selects:
                if isinstance(s, exp.Select):
                    scope = self._build_scope(s)
                    self._extract_joins(s, scope, result)
                    self._extract_cooccurrence(s, scope, result)

    # ── Scope ──────────────────────────────────────────────────

    def _build_scope(self, node: exp.Expression) -> Scope:
        scope = Scope()

        # Register schema map entries as defaults
        for alias, fqn in self.schema_map.items():
            scope.register(alias, fqn)

        # FROM tables
        for table in node.find_all(exp.Table):
            alias = table.alias
            physical = table.name
            if alias:
                scope.register(alias, physical)

        # CTEs
        ctes = node.args.get("with")
        if ctes:
            for cte in ctes.expressions:
                alias = cte.args.get("alias")
                if alias:
                    scope.register(alias.name, f"__cte__.{alias.name}")

        return scope

    @staticmethod
    def _ordered_key(a: str, b: str) -> tuple[str, str]:
        return (a, b) if a < b else (b, a)

    def _resolve_column(self, column: exp.Column, scope: Scope) -> tuple[str, str] | None:
        table_name = column.table
        col_name = column.name
        if not col_name:
            return None
        resolved_table = scope.resolve(table_name) if table_name else table_name
        if not resolved_table or resolved_table.startswith("__cte__"):
            return None
        # Try schema_map if resolved_table is still a bare name
        fqn_table = self.schema_map.get(resolved_table.lower(), resolved_table)
        return (fqn_table, col_name)

    def _to_fqn(self, table: str, col: str) -> str:
        return f"{table}.{col}"

    # ── JOIN extraction ────────────────────────────────────────

    def _extract_joins(self, node: exp.Select, scope: Scope, result: ParseResult):
        for join in node.find_all(exp.Join):
            side = (join.args.get("side") or "").strip()
            kind = (join.args.get("kind") or "").strip()
            join_type = side or kind or "INNER"
            on_node = join.args.get("on")
            if not on_node:
                continue

            eq_pairs = self._extract_equalities(on_node)
            for (left, right) in eq_pairs:
                resolved_left = self._resolve_column(left, scope)
                resolved_right = self._resolve_column(right, scope)
                if resolved_left and resolved_right:
                    fqn_left = self._to_fqn(*resolved_left)
                    fqn_right = self._to_fqn(*resolved_right)
                    result.joins.append(
                        JoinEvidence(
                            src_col_fqn=fqn_left,
                            dst_col_fqn=fqn_right,
                            join_type=join_type,
                            context_sql=join.sql(),
                        )
                    )

    @staticmethod
    def _extract_equalities(node: exp.Expression) -> list[tuple]:
        results = []
        for eq in node.find_all(exp.EQ):
            if isinstance(eq.left, exp.Column) and isinstance(eq.right, exp.Column):
                results.append((eq.left, eq.right))
            elif isinstance(eq.left, exp.Column) and isinstance(eq.right, exp.Cast):
                if isinstance(eq.right.this, exp.Column):
                    results.append((eq.left, eq.right.this))
            elif isinstance(eq.left, exp.Cast) and isinstance(eq.right, exp.Column):
                if isinstance(eq.left.this, exp.Column):
                    results.append((eq.left.this, eq.right))
        return results

    # ── Lineage (INSERT INTO ... SELECT) ───────────────────────

    def _extract_lineage_insert(self, stmt: exp.Insert, scope: Scope, result: ParseResult):
        target = stmt.args.get("this")
        if target is None:
            return

        if isinstance(target, exp.Schema):
            target_table = target.this
            insert_cols = list(target.expressions)
        elif isinstance(target, exp.Table):
            target_table = target
            insert_cols = []
        else:
            return

        target_name = target_table.name
        target_fqn = self.schema_map.get(target_name.lower(), target_name)

        select = stmt.args.get("expression")
        if not isinstance(select, exp.Select):
            return

        select_exprs = select.args.get("expressions", [])

        for i, sel_expr in enumerate(select_exprs):
            src_col = None
            if isinstance(sel_expr, exp.Column):
                src_col = sel_expr
            else:
                for col in sel_expr.find_all(exp.Column):
                    src_col = col
                    break

            if src_col is None:
                continue

            resolved = self._resolve_column(src_col, scope)
            if resolved is None:
                continue

            target_col = insert_cols[i].name if i < len(insert_cols) else src_col.name
            dst_fqn = self._to_fqn(target_fqn, target_col)
            result.lineages.append(
                LineageEvidence(
                    src_col_fqn=self._to_fqn(*resolved),
                    dst_col_fqn=dst_fqn,
                    transform=sel_expr.sql(),
                    context_sql=stmt.sql(),
                )
            )

    def _extract_lineage_update(self, stmt: exp.Update, scope: Scope, result: ParseResult):
        target = stmt.args.get("this")
        if not isinstance(target, exp.Table):
            return
        target_fqn = self.schema_map.get(target.name.lower(), target.name)

        for eq in stmt.find_all(exp.EQ):
            if isinstance(eq.left, exp.Column) and isinstance(eq.right, exp.Column):
                src = self._resolve_column(eq.right, scope)
                if src:
                    dst_fqn = self._to_fqn(target_fqn, eq.left.name)
                    result.lineages.append(
                        LineageEvidence(
                            src_col_fqn=self._to_fqn(*src),
                            dst_col_fqn=dst_fqn,
                            transform=eq.right.sql(),
                            context_sql=stmt.sql(),
                        )
                    )

    # ── Co-occurrence ──────────────────────────────────────────

    @staticmethod
    def _extract_cooccurrence(node: exp.Select, scope: Scope, result: ParseResult):
        tables = set()
        for table in node.find_all(exp.Table):
            name = table.name
            tables.add(name)
        if len(tables) >= 2:
            result.cooccurrences.append(CooccurrenceEvidence(list(tables)))


# ── Fallback regex parser for dynamic SQL ────────────────────────


def regex_extract_tables(sql: str) -> set[str]:
    """Extract table names via regex when sqlglot fails on dynamic SQL."""
    pattern = re.compile(
        r"(?:FROM|JOIN|INTO|UPDATE|TABLE)\s+([\"\']?)(\w+)\1",
        re.IGNORECASE,
    )
    return {m.group(2) for m in pattern.finditer(sql)}
