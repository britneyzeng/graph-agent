"""Cross-file aggregation of mining evidence.

Aggregates raw ParseResult across thousands of SQL files into:
  - FIELD_LINK (colA → colB): join co-occurrence / lineage
  - ENTITY_LINK (tableA → tableB): table co-occurrence
"""

from __future__ import annotations

import logging
import math
from collections import Counter

from mining.sql_parser import ParseResult

logger = logging.getLogger(__name__)


class AggregatedJoin:
    def __init__(self, src_fqn: str, dst_fqn: str):
        self.src_fqn = src_fqn
        self.dst_fqn = dst_fqn
        self.frequency = 0
        self.join_types: Counter = Counter()
        self.evidence_sqls: list[str] = []

    def add(self, evidence):
        self.frequency += 1
        self.join_types[evidence.join_type] += 1
        if len(self.evidence_sqls) < 5:
            self.evidence_sqls.append(evidence.context_sql[:200])

    @property
    def confidence(self) -> float:
        return min(1.0, self.frequency / 3.0)

    def to_dict(self) -> dict:
        return {"src_fqn": self.src_fqn, "dst_fqn": self.dst_fqn}


class AggregatedLineage:
    def __init__(self, src_fqn: str, dst_fqn: str):
        self.src_fqn = src_fqn
        self.dst_fqn = dst_fqn
        self.frequency = 0
        self.transforms: set[str] = set()
        self.proc_refs: list[str] = []
        self.evidence_sqls: list[str] = []

    def add(self, evidence, proc_name: str = ""):
        self.frequency += 1
        self.transforms.add(evidence.transform)
        if proc_name and proc_name not in self.proc_refs:
            self.proc_refs.append(proc_name)
        if len(self.evidence_sqls) < 5:
            self.evidence_sqls.append(evidence.context_sql[:200])

    def to_dict(self) -> dict:
        return {"src_fqn": self.src_fqn, "dst_fqn": self.dst_fqn}


class AggregatedCooccurrence:
    def __init__(self, table_a: str, table_b: str):
        self.table_a = table_a
        self.table_b = table_b
        self.count = 0
        self.properties: dict = {}

    @property
    def pmi(self) -> float:
        return self.properties.get("pmi", 0.0)

    def to_dict(self) -> dict:
        return {"src_fqn": self.table_a, "dst_fqn": self.table_b}


class RelationAggregator:
    def __init__(self, total_proc_count: int = 0):
        self.total_proc_count = total_proc_count
        self.joins: dict[tuple[str, str], AggregatedJoin] = {}
        self.lineages: dict[tuple[str, str], AggregatedLineage] = {}
        self.cooccurrences: dict[tuple[str, str], AggregatedCooccurrence] = {}
        self.table_freq: Counter = Counter()

    @staticmethod
    def _ordered_key(a: str, b: str) -> tuple[str, str]:
        return (a, b) if a < b else (b, a)

    def get_joins(self, min_freq: int = 2) -> list[AggregatedJoin]:
        return [j for j in self.joins.values() if j.frequency >= min_freq]

    def get_lineage(self) -> list[AggregatedLineage]:
        return list(self.lineages.values())

    def get_cooccurrences(self, min_pmi: float = 0.0) -> list[AggregatedCooccurrence]:
        result = []
        for coc in self.cooccurrences.values():
            pmi = coc.properties.get("pmi", 0)
            if pmi >= min_pmi:
                result.append(coc)
        return result

    def add_result(self, result: ParseResult, proc_name: str = ""):
        for je in result.joins:
            key = self._ordered_key(je.src_col_fqn, je.dst_col_fqn)
            if key not in self.joins:
                self.joins[key] = AggregatedJoin(je.src_col_fqn, je.dst_col_fqn)
            self.joins[key].add(je)

        for le in result.lineages:
            key = (le.src_col_fqn, le.dst_col_fqn)
            if key not in self.lineages:
                self.lineages[key] = AggregatedLineage(le.src_col_fqn, le.dst_col_fqn)
            self.lineages[key].add(le, proc_name)

        for ce in result.cooccurrences:
            for a, b in ce.pairs():
                key = self._ordered_key(a, b)
                if key not in self.cooccurrences:
                    self.cooccurrences[key] = AggregatedCooccurrence(a, b)
                self.cooccurrences[key].count += 1
            for t in ce.table_fqns:
                self.table_freq[t] += 1

    def compute_pmi(self):
        total = self.total_proc_count or max(
            (sum(self.table_freq.values()) // max(len(self.table_freq), 1)), 1
        )
        for key, coc in self.cooccurrences.items():
            a, b = key
            pa = self.table_freq.get(a, 1) / total
            pb = self.table_freq.get(b, 1) / total
            pab = coc.count / total
            if pa > 0 and pb > 0 and pab > 0:
                pmi = math.log2(pab / (pa * pb))
            else:
                pmi = 0.0
            coc.properties["pmi"] = round(pmi, 4)
            coc.properties["total_procs"] = total

    def to_relationship_dicts(self, min_join_freq: int = 2, min_pmi: float = 0.0) -> list[dict]:
        rows = []

        for join in self.joins.values():
            if join.frequency < min_join_freq:
                continue
            rows.append(join.to_dict())

        for lineage in self.lineages.values():
            rows.append(lineage.to_dict())

        for coc in self.cooccurrences.values():
            pmi = coc.properties.get("pmi", 0)
            if pmi < min_pmi:
                continue
            rows.append(coc.to_dict())

        return rows
