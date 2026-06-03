"""每日风险检查：按 Louvain 社区分组，检查实体间 FK 数据一致性。

逻辑:
  1. 从 Kuzu 读取 Entity、Field 及其 community_id
  2. 社区 = FK 连接紧密的字段组，映射到对应的实体组
  3. 按社区做跨表 FK 孤立记录检查
  4. 跨多社区的实体 = 桥梁实体，风险权重更高

用法:
    python -m scripts.daily_risk_check
    python -m scripts.daily_risk_check --output report.json
    python -m scripts.daily_risk_check --mock              # 模拟 PG 数据
    python -m scripts.daily_risk_check --mock --output report.json
"""

import argparse
import json
import logging
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("daily_risk_check")


class MockPgClient:
    """模拟 PostgreSQL 客户端，返回合成数据用于演示。"""

    _table_row_counts: dict[str, int] = {
        "supplier": 50,
        "po_order": 200,
        "po_line": 850,
        "material": 120,
        "inventory": 120,
        "invoice": 180,
        "invoice_line": 720,
        "vendor_eval": 30,
    }

    _orphan_fk: dict[tuple[str, str], list[dict]] = {
        ("po_order", "supplier"): [
            {"po_order_id": 42, "supplier_id": 999},
            {"po_order_id": 77, "supplier_id": 888},
            {"po_order_id": 91, "supplier_id": 777},
        ],
        ("invoice", "po_order"): [
            {"invoice_id": 15, "po_order_id": 9999},
        ],
        ("invoice_line", "po_line"): [
            {"invoice_line_id": 301, "po_line_id": 99901},
            {"invoice_line_id": 302, "po_line_id": 99902},
        ],
    }

    async def execute(self, sql: str) -> list[dict]:
        sql_lower = sql.strip().lower()

        if sql_lower.startswith("select count("):
            for tbl, cnt in self._table_row_counts.items():
                if tbl in sql_lower:
                    return [{"cnt": cnt}]
            return [{"cnt": 0}]

        if sql_lower.startswith("select") and "left join" in sql_lower and "is null" in sql_lower:
            for (src, dst), rows in self._orphan_fk.items():
                if src in sql_lower and dst in sql_lower:
                    return rows
            return []

        return []


async def _run_pg(pg_client: Any, sql: str) -> list[dict]:
    """调用 PG 的封装，便于统一处理异常。"""
    return await pg_client.execute(sql)


def load_kuzu() -> dict[str, Any]:
    from kuzu_client import get_kuzu_client
    c = get_kuzu_client()

    entities = c.execute("""
        MATCH (e:Entity)
        RETURN e.fqn AS fqn, e.name_cn AS name_cn,
               e.src_tables AS src_tables
    """)

    fields = c.execute("""
        MATCH (c:Field)
        RETURN c.fqn AS fqn, c.name AS name,
               c.entity_fqn AS entity_fqn,
               c.ref_property_fqn AS ref_property_fqn,
               c.community_id AS community_id
    """)

    return {"entities": entities, "fields": fields}


def build_communities(data: dict[str, Any]) -> list[dict[str, Any]]:
    entities = {e["fqn"]: e for e in data["entities"]}
    field_to_entity = {f["fqn"]: f["entity_fqn"] for f in data["fields"]}

    entity_fk: set[tuple[str, str]] = set()
    for f in data["fields"]:
        ref = f.get("ref_property_fqn")
        if not ref:
            continue
        dst_entity = field_to_entity.get(ref)
        if dst_entity and f["entity_fqn"] != dst_entity:
            entity_fk.add((f["entity_fqn"], dst_entity))

    communities: dict[int, dict] = {}
    for f in data["fields"]:
        cid = f.get("community_id")
        if cid is None:
            continue
        if cid not in communities:
            communities[cid] = {"community_id": cid, "field_count": 0, "entity_fqns": set(), "fields": []}
        communities[cid]["field_count"] += 1
        communities[cid]["fields"].append(f["fqn"])
        communities[cid]["entity_fqns"].add(f["entity_fqn"])

    entity_community_count: dict[str, int] = defaultdict(int)
    for c in communities.values():
        for efqn in c["entity_fqns"]:
            entity_community_count[efqn] += 1

    results = []
    for cid, c in sorted(communities.items()):
        entity_fqns = list(c["entity_fqns"])
        if len(entity_fqns) < 2:
            continue

        chain_entities = [entities[efqn] for efqn in entity_fqns if efqn in entities]
        if not chain_entities:
            continue

        pairs_in_comm = [(s, d) for s, d in entity_fk if s in entity_fqns and d in entity_fqns]
        if not pairs_in_comm:
            continue

        results.append({
            "community_id": cid,
            "field_count": c["field_count"],
            "entities": [{
                "fqn": e["fqn"],
                "name_cn": e["name_cn"],
                "pg_table": e["src_tables"][0].split(".")[-1] if e.get("src_tables") else None,
                "bridge_score": entity_community_count.get(e["fqn"], 1),
            } for e in sorted(chain_entities,
                               key=lambda x: entity_community_count.get(x["fqn"], 1), reverse=True)],
            "fk_pairs": [{"src": entities[s]["name_cn"], "dst": entities[d]["name_cn"]} for s, d in pairs_in_comm],
            "entity_names": [e["name_cn"] for e in chain_entities],
        })

    results.sort(key=lambda c: len(c["entities"]), reverse=True)
    return results


async def run_checks(pg_client: Any, community: dict[str, Any]) -> dict[str, Any]:
    results = []
    for pair in community["fk_pairs"]:
        src_table = next((e["pg_table"] for e in community["entities"] if e["name_cn"] == pair["src"]), None)
        dst_table = next((e["pg_table"] for e in community["entities"] if e["name_cn"] == pair["dst"]), None)
        if not src_table or not dst_table:
            continue

        try:
            rows = await _run_pg(pg_client, f"SELECT COUNT(*) AS cnt FROM {src_table}")
            src_cnt = rows[0]["cnt"]

            fk_col = f"{pair['dst'].lower()}_id"
            orphan_sql = (
                f"SELECT {src_table}.{fk_col} "
                f"FROM {src_table} LEFT JOIN {dst_table} "
                f"ON {src_table}.{fk_col} = {dst_table}.{fk_col} "
                f"WHERE {dst_table}.{fk_col} IS NULL"
            )
            orphans = await _run_pg(pg_client, orphan_sql)

            status = "ok" if not orphans else "risk"
            results.append({
                "check": f"{pair['src']}→{pair['dst']} FK",
                "status": status,
                "src_row_count": src_cnt,
                "orphan_count": len(orphans),
                "detail": f"{len(orphans)}/{src_cnt} 条孤立记录" if orphans else f"{src_cnt} 条记录，FK 完整",
            })
        except Exception as e:
            results.append({"check": f"{pair['src']}→{pair['dst']} FK", "status": "error", "detail": str(e)})

    bridge_link_text = " | ".join(
        f"{e['name_cn']}(跨{ e['bridge_score'] }个社区)"
        for e in sorted(community["entities"], key=lambda x: x["bridge_score"], reverse=True)
    )

    return {
        "community_id": community["community_id"],
        "field_count": community["field_count"],
        "entities": [e["name_cn"] for e in community["entities"]],
        "bridge_info": bridge_link_text,
        "fk_checks": results,
        "risk_count": sum(1 for r in results if r.get("status") == "risk"),
    }


async def main():
    parser = argparse.ArgumentParser(description="每日数据风险检查")
    parser.add_argument("--output", default=None)
    parser.add_argument("--mock", action="store_true", help="模拟 PostgreSQL 返回结果")
    args = parser.parse_args()

    data = load_kuzu()
    communities = build_communities(data)

    if not communities:
        _output_report({"date": str(date.today()), "status": "empty", "communities": []}, args.output)
        return

    logger.info("发现 %d 个 FK 业务社区:", len(communities))
    for c in communities:
        logger.info("  社区 %d (%d 字段): %s",
                    c["community_id"], c["field_count"], " ↔ ".join(c["entity_names"]))

    if args.mock:
        pg = MockPgClient()
        logger.info("使用模拟 PostgreSQL 客户端")
    else:
        try:
            from pg_client import get_pg_client
            pg = get_pg_client()
        except Exception as e:
            logger.error("PostgreSQL 不可用: %s", e)
            logger.info("使用 --mock 参数可模拟 PG 返回结果进行演示")
            _output_report({
                "date": str(date.today()),
                "status": "error",
                "message": str(e),
                "communities": communities,
            }, args.output)
            return

    results = []
    for c in communities:
        logger.info("检查社区 %d: %s", c["community_id"], " ↔ ".join(c["entity_names"]))
        results.append(await run_checks(pg, c))

    _output_report({
        "date": str(date.today()),
        "status": "ok",
        "total_risks": sum(r["risk_count"] for r in results),
        "communities": results,
    }, args.output)


def _output_report(report: dict, output_path: str | None = None) -> None:
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if output_path:
        Path(output_path).write_text(text, encoding="utf-8")
        logger.info("报告已写入 %s", output_path)
    else:
        print(text)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
