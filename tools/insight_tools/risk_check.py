import json
import logging
from collections.abc import AsyncGenerator

from neo4j_client import Neo4jClientError, get_neo4j_client
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class RiskCheckParams(BaseModel):
    check_type: str = Field(
        "all",
        description="Type: orphan_fk (FK points nowhere), cross_domain (FK spans domains), missing_pk",
    )
    domain: str | None = Field(None, description="Domain code to scope the check")


TOOL = {
    "name": "risk_check",
    "display_name": "Risk Check",
    "display_name_locale": {"zh": "数据风险检查"},
    "description": "Run quality check rules against the Neo4j schema graph to detect data risks",
    "description_locale": {
        "zh": "在 Neo4j Schema 图上运行质量检查规则，检测 orphan FK、跨域引用、缺主键等风险"
    },
    "params_model": RiskCheckParams,
}


RULES = {
    "orphan_fk": {
        "name": "Orphan Foreign Key",
        "zh": "外键无对应主表",
        "query": """
            MATCH (fk:Column)
            WHERE fk.is_fk = true AND (fk.ref_column_fqn IS NULL OR fk.ref_column_fqn = '')
            {domain_filter}
            RETURN fk.fqn AS col_fqn, fk.name AS col_name,
                   'is_fk=true but ref_column_fqn is empty' AS detail
        """,
        "domain_var": "fk",
    },
    "cross_domain": {
        "name": "Cross-Domain Reference",
        "zh": "跨领域外键引用",
        "query": """
            MATCH (c1:Column)-[:REFERENCES]->(c2:Column)
            WHERE c1.domains <> c2.domains
            {domain_filter}
            RETURN c1.fqn AS col_fqn, c2.fqn AS ref_col_fqn,
                   c1.domains AS src_domains, c2.domains AS dst_domains,
                   'domains differ' AS detail
        """,
        "domain_var": "c1",
    },
    "missing_pk": {
        "name": "Table Without Primary Key",
        "zh": "表缺少主键",
        "query": """
            MATCH (t:Table)
            OPTIONAL MATCH (t)-[:HAS_COLUMN]->(pk:Column {is_pk: true})
            WITH t, collect(pk) AS pks
            WHERE size(pks) = 0
            {domain_filter}
            RETURN t.fqn AS col_fqn, t.name AS col_name,
                   'no column marked as PK' AS detail
        """,
        "domain_var": "t",
    },
}


async def execute(args: dict) -> AsyncGenerator[str, None]:
    check_type = args.get("check_type", "all")
    domain = args.get("domain")

    try:
        client = get_neo4j_client()

        check_types = list(RULES.keys()) if check_type == "all" else [check_type]
        issues = []

        for ct in check_types:
            rule = RULES.get(ct)
            if not rule:
                continue

            yield json.dumps(
                {"status": "progress", "message": f"Running check: {rule['zh']} ..."},
                ensure_ascii=False,
            )

            q = rule["query"]
            if domain:
                var = rule["domain_var"]
                domain_clause = f"AND ${var}_dom IN {var}.domains"
                q = q.replace("{domain_filter}", domain_clause)
                params = {f"{var}_dom": domain}
            else:
                q = q.replace("{domain_filter}", "")
                params = {}

            rows = await client.execute_schema(q, params)
            for r in rows:
                issues.append(
                    {
                        "type": ct,
                        "rule_name": rule["zh"],
                        "col_fqn": r.get("col_fqn", ""),
                        "detail": r.get("detail", ""),
                    }
                )

        yield json.dumps(
            {
                "success": True,
                "data": {
                    "check_type": check_type,
                    "domain": domain,
                    "total_issues": len(issues),
                    "issues": issues,
                },
            },
            ensure_ascii=False,
        )

    except Neo4jClientError as e:
        logger.exception("Neo4j error")
        yield json.dumps({"success": False, "error": f"Database error: {e}"}, ensure_ascii=False)
    except Exception as e:
        logger.exception("Risk check error")
        yield json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)
