from __future__ import annotations

import json
import logging

try:
    from kuzu_client import get_kuzu_client
except ImportError:
    get_kuzu_client = None

from builder.schema import NT, NP, ensure_schema
from registry.models import RegistryData

logger = logging.getLogger(__name__)


class GraphBuilder:
    BATCH_SIZE = 500

    def __init__(self, registry: RegistryData):
        self.registry = registry

    def _client(self):
        if get_kuzu_client is None:
            raise RuntimeError("kuzu-client package not available")
        return get_kuzu_client()

    async def _run(self, query: str, params: dict | None = None):
        self._client().execute(query, params or {})

    async def _sync_domains(self):
        query = f"""
            UNWIND $batch AS d
            MERGE (n:Domain {{code: d.code}})
            SET n.fqn = d.code,
                n.name_cn = d.name_cn,
                n.name_en = d.name_en,
                n.parent_code = d.parent_code,
                n.description = d.description,
                n.source = d.source,
                n.status = d.status
        """
        batch = [
            {
                "code": d.code,
                "name_cn": d.name_cn,
                "name_en": d.name_en or "",
                "parent_code": d.parent_code or "",
                "description": d.description,
                "source": d.source,
                "status": d.status,
            }
            for d in self.registry.domains
        ]
        await self._run(query, {"batch": batch})
        logger.info("Synced %d Domain nodes", len(batch))

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
        skipped = [e.fqn for e in self.registry.entities if e.status == "active" and not e.entity_type]
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
            q = f"MATCH (s:{NT} {{fqn: $src}}), (d:Domain {{code: $dst}}) MERGE (s)-[:IN_DOMAIN {{source: 'registry', status: 'active'}}]->(d)"
            await self._run(q, {"src": src, "dst": dst})

    async def _sync_properties(self):
        query = f"""
            UNWIND $batch AS row
            MATCH (e:{NT} {{fqn: row.entity_fqn}})
            MERGE (p:{NP} {{fqn: row.fqn}})
            SET p.name = row.name,
                p.data_type = row.data_type,
                p.is_pk = row.is_pk,
                p.is_fk = row.is_fk,
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
                "is_fk": p.is_fk,
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

    async def _enrich_entities(self):
        active_entities = [e for e in self.registry.entities if e.status == "active"]
        if not active_entities:
            return

        batch = []
        for e in active_entities:
            props = [p for p in self.registry.properties if p.entity_fqn == e.fqn]
            pk_names = [p.name for p in props if p.is_pk]
            fk_names = [p.name for p in props if p.is_fk and p.ref_property_fqn]
            properties = {p.name: p.data_type for p in props}
            batch.append({
                "fqn": e.fqn,
                "property_count": len(props),
                "pk_properties": pk_names,
                "fk_properties": fk_names,
                "has_pk": len(pk_names) > 0,
                "has_fk": len(fk_names) > 0,
                "properties": json.dumps(properties, ensure_ascii=False),
            })

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

    async def _sync_fk_relationships(self):
        active_entity_fqns = {e.fqn for e in self.registry.entities if e.status == "active"}
        fk_properties = [
            p for p in self.registry.properties
            if p.is_fk and p.ref_property_fqn and p.entity_fqn in active_entity_fqns
        ]
        if not fk_properties:
            return
        for p in fk_properties:
            q = f"""
                MATCH (src:{NP} {{fqn: $src_fqn}}), (dst:{NP} {{fqn: $dst_fqn}})
                MERGE (src)-[:REFERENCES {{source: 'fk_introspect', status: 'active'}}]->(dst)
            """
            await self._run(q, {"src_fqn": p.fqn, "dst_fqn": p.ref_property_fqn})
        logger.info("Auto-created %d FK relationships", len(fk_properties))

    async def _sync_relationships(self):
        auto_created_tables: set[str] = set()
        active_rels = [r for r in self.registry.relationships if r.status == "active"]
        if not active_rels:
            return

        for r in active_rels:
            if r.rel_type not in auto_created_tables:
                self._client().execute(
                    f"CREATE REL TABLE IF NOT EXISTS {r.rel_type}(FROM {NT} TO {NT})"
                )
                auto_created_tables.add(r.rel_type)
            q = f"""
                MATCH (src:{NT} {{fqn: $src_fqn}}), (dst:{NT} {{fqn: $dst_fqn}})
                MERGE (src)-[:{r.rel_type}]->(dst)
            """
            try:
                await self._run(q, {
                    "src_fqn": r.src_fqn,
                    "dst_fqn": r.dst_fqn,
                })
            except Exception as e:
                logger.warning("Failed to create relationship %s: %s", r.rel_type, e)
        logger.info("Processed %d manually-defined relationships", len(active_rels))

    async def sync_all(self):
        logger.info("Starting full graph sync ...")
        get_kuzu_client(recreate=True)
        ensure_schema(self._client())
        await self._sync_domains()
        await self._sync_entities()
        await self._sync_properties()
        await self._enrich_entities()
        await self._sync_fk_relationships()
        await self._sync_relationships()
        logger.info("Graph sync completed.")
