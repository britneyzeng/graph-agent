"""Tests for mining module - SQL parser and relation aggregator."""

from mining.relation_aggregator import RelationAggregator
from mining.sql_parser import CooccurrenceEvidence, JoinEvidence, LineageEvidence, ParseResult, SqlParser


class TestSqlParser:
    def test_parse_simple_join(self):
        sql = "SELECT * FROM po_order o JOIN supplier s ON o.supplier_id = s.id"
        parser = SqlParser(schema_map={"po_order": "db.public.po_order", "supplier": "db.public.supplier"})
        result = parser.parse_string(sql)

        assert len(result.joins) >= 1
        j = result.joins[0]
        assert "supplier_id" in j.src_col_fqn or "supplier_id" in j.dst_col_fqn

    def test_parse_insert_select(self):
        sql = """
            INSERT INTO po_order_hist(id, order_no, total_amt)
            SELECT src.id, src.order_no, src.total_amt
            FROM po_order src
            WHERE src.status = 'closed'
        """
        parser = SqlParser(schema_map={
            "po_order": "db.public.po_order",
            "po_order_hist": "db.public.po_order_hist",
        })
        result = parser.parse_string(sql)
        assert len(result.lineages) >= 1

    def test_parse_join_type(self):
        sql = """
            SELECT a.order_no, b.name
            FROM po_order a
            LEFT JOIN supplier b ON a.supplier_id = b.id
        """
        parser = SqlParser(schema_map={
            "po_order": "db.public.po_order",
            "supplier": "db.public.supplier",
        })
        result = parser.parse_string(sql)
        assert len(result.joins) >= 1
        assert result.joins[0].join_type == "LEFT"

    def test_cooccurrence_extraction(self):
        sql = """
            SELECT * FROM po_order o, supplier s, contract c
            WHERE o.supplier_id = s.id AND o.contract_id = c.id
        """
        parser = SqlParser()
        result = parser.parse_string(sql)
        assert len(result.cooccurrences) >= 1
        pairs = list(result.cooccurrences[0].pairs())
        assert len(pairs) >= 3

    def test_fallback_regex(self):
        from mining.sql_parser import regex_extract_tables

        tables = regex_extract_tables("SELECT * FROM po_order JOIN supplier ON ...")
        assert "po_order" in tables
        assert "supplier" in tables

    def test_bad_sql_does_not_crash(self):
        parser = SqlParser()
        result = parser.parse_string("SELECT FROM WHERE 1=1")
        assert result.error is not None or result.parsed is True

    def test_empty_sql(self):
        parser = SqlParser()
        result = parser.parse_string("")
        assert result.joins == []


class TestRelationAggregator:
    def test_aggregate_joins(self):
        agg = RelationAggregator()
        result = ParseResult("a.sql")
        result.joins.append(JoinEvidence(
            src_col_fqn="db.t1.c1", dst_col_fqn="db.t2.c2",
            join_type="INNER", context_sql="SELECT ...",
        ))
        result.joins.append(JoinEvidence(
            src_col_fqn="db.t1.c1", dst_col_fqn="db.t2.c2",
            join_type="LEFT", context_sql="SELECT ...",
        ))
        agg.add_result(result)
        rows = agg.to_relationship_dicts(min_join_freq=1)
        assert len(rows) == 1
        assert rows[0]["properties"]["frequency"] == 2

    def test_aggregate_lineage(self):
        agg = RelationAggregator()
        result = ParseResult("a.sql")
        result.lineages.append(LineageEvidence(
            src_col_fqn="db.t1.c1", dst_col_fqn="db.t2.c2",
            transform="c1 * 2", context_sql="INSERT INTO ...",
        ))
        agg.add_result(result)
        rows = agg.to_relationship_dicts()
        lineage_rows = [r for r in rows if r["rel_type"] == "DERIVES_FROM"]
        assert len(lineage_rows) == 1

    def test_aggregate_cooccurrence(self):
        agg = RelationAggregator(total_proc_count=10)
        result = ParseResult("a.sql")
        from mining.sql_parser import CooccurrenceEvidence

        result.cooccurrences.append(CooccurrenceEvidence(["t1", "t2"]))
        result.cooccurrences.append(CooccurrenceEvidence(["t1", "t2"]))
        result.cooccurrences.append(CooccurrenceEvidence(["t1", "t3"]))

        agg.add_result(result)
        agg.compute_pmi()
        rows = agg.to_relationship_dicts(min_pmi=-999)
        coc_rows = [r for r in rows if r["rel_type"] == "CO_USED_WITH"]
        assert len(coc_rows) >= 2
