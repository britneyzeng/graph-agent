from __future__ import annotations

import json
import logging

try:
    from kuzu_client import get_kuzu_client
except ImportError:
    get_kuzu_client = None

from builder.schema import NL, NP, NT, ensure_schema
from registry.models import RegistryData

logger = logging.getLogger(__name__)


class GraphBuilder:
    BATCH_SIZE = 500

    # Map (src_type, dst_type) pairs to the canonical Kuzu rel table name
    _REL_TABLE_MAP: dict[tuple[str, str], str] = {
        ("Entity", "Domain"): "IN_DOMAIN",
        ("Entity", "Field"): "HAS_PROPERTY",
        ("Logic", "Field"): "COMPUTES",
        ("Logic", "Logic"): "LOGIC_LINK",
        ("Entity", "Entity"): "ENTITY_LINK",
        ("Domain", "Domain"): "DOMAIN_LINK",
        ("Field", "Field"): "FIELD_LINK",
        ("Entity", "Logic"): "USE_LOGIC",
        ("Domain", "Logic"): "HAS_LOGIC",
    }

    def __init__(self, registry: RegistryData):
        self.registry = registry

    def _client(self):
        if get_kuzu_client is None:
            raise RuntimeError("kuzu-client package not available")
        return get_kuzu_client()

    async def _run(self, query: str, params: dict | None = None):
        self._client().execute(query, params or {})

    async def sync_all(self):
        logger.info("Starting full graph sync ...")
        get_kuzu_client(recreate=True)
        ensure_schema(self._client())
        await self._sync_domains()
        await self._sync_entities()
        await self._sync_properties()
        await self._sync_logics()
        await self._enrich_entities()
        await self._sync_domain_links()
        await self._sync_fk_field_links()
        await self._sync_computes()
        await self._sync_logic_links()
        await self._sync_relationships()
        logger.info("Graph sync completed.")

    # ── Domain ──

    async def _sync_domains(self):
        query = """
            UNWIND $batch AS d
            MERGE (n:Domain {fqn: d.fqn})
            SET n.name_cn = d.name_cn,
                n.name_en = d.name_en,
                n.parent_fqn = d.parent_fqn,
                n.description = d.description,
                n.source = d.source,
                n.status = d.status
        """
        batch = [
            {
                "fqn": d.fqn,
                "name_cn": d.name_cn,
                "name_en": d.name_en or "",
                "parent_fqn": d.parent_fqn or "",
                "description": d.description,
                "source": d.source,
                "status": d.status,
            }
            for d in self.registry.domains
        ]
        await self._run(query, {"batch": batch})
        logger.info("Synced %d Domain nodes", len(batch))

    async def _sync_domain_links(self):
        """parent_fqn → DOMAIN_LINK"""
        for d in self.registry.domains:
            if not d.parent_fqn:
                continue
            q = """
                MATCH (parent:Domain {fqn: $parent}), (child:Domain {fqn: $code})
                MERGE (child)-[:DOMAIN_LINK {source: 'registry', status: 'active'}]->(parent)
            """
            await self._run(q, {"parent": d.parent_fqn, "code": d.fqn})

    # ── Entity ──

    async def _sync_entities(self):
        query = f"""
            UNWIND $batch AS e
            MERGE (n:{NT} {{fqn: e.fqn}})
            SET n.entity_type = e.entity_type,
                n.name_cn = e.name_cn,
                n.name_en = e.name_en,
                n.src_tables = e.src_tables,
                n.domains = e.domains,
                n.description = e.description,
                n.source = e.source,
                n.status = e.status
        """
        skipped = [
            e.fqn for e in self.registry.entities if e.status == "active" and not e.entity_type
        ]
        if skipped:
            logger.warning("Skipping %d entities without entity_type: %s", len(skipped), skipped)
        batch = [
            {
                "fqn": e.fqn,
                "entity_type": e.entity_type,
                "name_cn": e.name_cn,
                "name_en": e.name_en or "",
                "src_tables": e.src_tables,
                "domains": e.domains,
                "description": e.description,
                "source": e.source,
                "status": e.status,
            }
            for e in self.registry.entities
            if e.status == "active" and e.entity_type
        ]
        await self._run(query, {"batch": batch})
        await self._sync_in_domain(batch)
        logger.info("Synced %d Entity nodes", len(batch))

    async def _sync_in_domain(self, entity_batch: list[dict]):
        rels = [(e["fqn"], dc) for e in entity_batch for dc in e.get("domains", [])]
        if not rels:
            return
        for src, dst in rels:
            q = f"MATCH (s:{NT} {{fqn: $src}}), (d:Domain {{fqn: $dst}}) MERGE (s)-[:IN_DOMAIN {{source: 'registry', status: 'active'}}]->(d)"
            await self._run(q, {"src": src, "dst": dst})

    # ── Property ──

    async def _sync_properties(self):
        query = f"""
            UNWIND $batch AS row
            MATCH (e:{NT} {{fqn: row.entity_fqn}})
            MERGE (p:{NP} {{fqn: row.fqn}})
            SET p.name = row.name,
                p.data_type = row.data_type,
                p.is_pk = row.is_pk,
                p.ref_property_fqn = row.ref_property_fqn,
                p.description = row.description,
                p.name_cn = row.name_cn,
                p.name_en = row.name_en,
                p.source = row.source,
                p.status = row.status,
                p.entity_fqn = row.entity_fqn
            MERGE (e)-[:HAS_PROPERTY]->(p)
        """
        active_entity_fqns = {e.fqn for e in self.registry.entities if e.status == "active"}
        batch = [
            {
                "fqn": p.fqn,
                "entity_fqn": p.entity_fqn,
                "name": p.name,
                "data_type": p.data_type,
                "is_pk": p.is_pk,
                "ref_property_fqn": p.ref_property_fqn or "",
                "description": p.description,
                "name_cn": p.name_cn,
                "name_en": p.name_en or "",
                "source": p.source,
                "status": p.status,
            }
            for p in self.registry.properties
            if p.entity_fqn in active_entity_fqns
        ]
        for i in range(0, len(batch), self.BATCH_SIZE):
            await self._run(query, {"batch": batch[i : i + self.BATCH_SIZE]})
        logger.info("Synced %d Property nodes + HAS_PROPERTY", len(batch))

    async def _sync_fk_field_links(self):
        """主键 → 外键: FIELD_LINK 方向为主键字段指向外键字段"""
        active_entity_fqns = {e.fqn for e in self.registry.entities if e.status == "active"}
        fk_props = [
            p
            for p in self.registry.properties
            if p.ref_property_fqn and p.entity_fqn in active_entity_fqns
        ]
        count = 0
        for p in fk_props:
            q = f"""
                MATCH (src:{NP} {{fqn: $src_fqn}}), (dst:{NP} {{fqn: $dst_fqn}})
                MERGE (src)-[:FIELD_LINK {{source: 'fk_introspect', status: 'active'}}]->(dst)
            """
            # 源: 主键字段 (ref_property_fqn), 目标: 外键字段 (p.fqn)
            await self._run(q, {"src_fqn": p.ref_property_fqn, "dst_fqn": p.fqn})
            count += 1
        if count:
            logger.info("Created %d FIELD_LINK from FK", count)

    # ── Entity enrichment ──

    async def _enrich_entities(self):
        active_entities = [e for e in self.registry.entities if e.status == "active"]
        if not active_entities:
            return

        batch = []
        for e in active_entities:
            props = [p for p in self.registry.properties if p.entity_fqn == e.fqn]
            pk_names = [p.name for p in props if p.is_pk]
            fk_names = [p.name for p in props if p.ref_property_fqn]
            properties = {p.name: p.data_type for p in props}
            batch.append(
                {
                    "fqn": e.fqn,
                    "property_count": len(props),
                    "pk_properties": pk_names,
                    "fk_properties": fk_names,
                    "has_pk": len(pk_names) > 0,
                    "has_fk": len(fk_names) > 0,
                    "properties": json.dumps(properties, ensure_ascii=False),
                }
            )

        query = f"""
            UNWIND $batch AS row
            MATCH (e:{NT} {{fqn: row.fqn}})
            SET e.property_count = row.property_count,
                e.pk_properties = row.pk_properties,
                e.fk_properties = row.fk_properties,
                e.has_pk = row.has_pk,
                e.has_fk = row.has_fk,
                e.properties = row.properties
        """
        await self._run(query, {"batch": batch})
        logger.info("Enriched %d entity nodes", len(batch))

    # ── Logic ──

    async def _sync_logics(self):
        query = f"""
            UNWIND $batch AS row
            MERGE (n:{NL} {{fqn: row.fqn}})
            SET n.logic_type = row.logic_type,
                n.expression = row.expression,
                n.name_cn = row.name_cn,
                n.name_en = row.name_en,
                n.description = row.description,
                n.source = row.source,
                n.status = row.status
        """
        batch = [
            {
                "fqn": l.fqn,
                "logic_type": l.logic_type,
                "expression": l.expression,
                "name_cn": l.name_cn,
                "name_en": l.name_en or "",
                "description": l.description,
                "source": l.source,
                "status": l.status,
            }
            for l in self.registry.logics
            if l.status == "active"
        ]
        if not batch:
            return
        await self._run(query, {"batch": batch})
        logger.info("Synced %d Logic nodes", len(batch))

    async def _sync_computes(self):
        """COMPUTES rel_type: Logic→Field (logic produces field)."""
        count = 0
        logic_fqns = {l.fqn for l in self.registry.logics if l.status == "active"}
        field_fqns = {p.fqn for p in self.registry.properties}

        for r in self.registry.relationships:
            if r.status != "active" or r.rel_type != "COMPUTES":
                continue
            if r.src_fqn not in logic_fqns or r.dst_fqn not in field_fqns:
                logger.warning(
                    "COMPUTES %s → %s: must be Logic→Field, skipped", r.src_fqn, r.dst_fqn
                )
                continue
            q = f"""
                MATCH (src:{NL} {{fqn: $src_fqn}}), (dst:{NP} {{fqn: $dst_fqn}})
                MERGE (src)-[:COMPUTES {{source: 'registry', status: 'active'}}]->(dst)
            """
            await self._run(q, {"src_fqn": r.src_fqn, "dst_fqn": r.dst_fqn})
            count += 1
        if count:
            logger.info("Synced %d COMPUTES edges", count)

    async def _sync_logic_links(self):
        """LOGIC_LINK rel_type in Relationship sheet"""
        count = 0
        for r in self.registry.relationships:
            if r.status != "active" or r.rel_type != "LOGIC_LINK":
                continue
            q = f"""
                MATCH (src:{NL} {{fqn: $src_fqn}}), (dst:{NL} {{fqn: $dst_fqn}})
                MERGE (src)-[:LOGIC_LINK {{source: 'registry', status: 'active'}}]->(dst)
            """
            await self._run(q, {"src_fqn": r.src_fqn, "dst_fqn": r.dst_fqn})
            count += 1
        if count:
            logger.info("Synced %d LOGIC_LINK edges", count)

    # ── General relationships → LINK tables ──

    async def _sync_relationships(self):
        """Map remaining RelationshipDef to appropriate LINK tables by (src_type, dst_type)."""
        entity_fqns = {e.fqn for e in self.registry.entities if e.status == "active"}
        field_fqns = {p.fqn for p in self.registry.properties}
        logic_fqns = {l.fqn for l in self.registry.logics if l.status == "active"}
        domain_codes = {d.fqn for d in self.registry.domains}

        def _resolve_type(fqn: str) -> str | None:
            if fqn in entity_fqns:
                return "Entity"
            if fqn in field_fqns:
                return "Field"
            if fqn in logic_fqns:
                return "Logic"
            if fqn in domain_codes:
                return "Domain"
            return None

        handled_special = {"COMPUTES", "LOGIC_LINK"}
        count = 0

        for r in self.registry.relationships:
            if r.status != "active":
                continue
            if r.rel_type in handled_special:
                continue

            src_type = _resolve_type(r.src_fqn)
            dst_type = _resolve_type(r.dst_fqn)
            if src_type is None or dst_type is None:
                logger.warning("Relationship %s: cannot resolve src/dst type, skipped", r.rel_type)
                continue

            table = self._REL_TABLE_MAP.get((src_type, dst_type))
            if table is None:
                logger.warning(
                    "Relationship %s: no LINK table for (%s → %s), skipped. "
                    "Canonical directions: Entity→Entity/Entity→Logic/Domain→Domain/Domain→Logic/Field→Field",
                    r.rel_type,
                    src_type,
                    dst_type,
                )
                continue

            q = f"""
                MATCH (src:{src_type} {{fqn: $src_fqn}}), (dst:{dst_type} {{fqn: $dst_fqn}})
                MERGE (src)-[:{table} {{source: $source, status: 'active'}}]->(dst)
            """
            await self._run(q, {"src_fqn": r.src_fqn, "dst_fqn": r.dst_fqn, "source": r.source})
            count += 1

        if count:
            logger.info("Synced %d LINK relationships", count)
