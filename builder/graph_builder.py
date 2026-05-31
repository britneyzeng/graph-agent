from __future__ import annotations

import logging

try:
    from neo4j_client import get_neo4j_client
except ImportError:
    get_neo4j_client = None

from registry.models import RegistryData

logger = logging.getLogger(__name__)


class GraphBuilder:
    """Project RegistryData onto Neo4j via idempotent MERGE.

    Most relationships are auto-created from Entity/Property metadata:
      - IN_DOMAIN     from ``EntityDef.domains`` / ``PropertyDef.domains``
      - HAS_PROPERTY  from ``PropertyDef.entity_fqn``
      - REFERENCES    from ``PropertyDef.is_fk + ref_property_fqn``

    The Relationship sheet provides *manual overrides*: any relationship
    defined there is merged via ``apoc.merge.relationship`` so its
    properties (source, status, …) take precedence over the auto-created
    values.
    """

    BATCH_SIZE = 500

    def __init__(self, registry: RegistryData):
        self.registry = registry

    def _client(self):
        if get_neo4j_client is None:
            raise RuntimeError("neo4j-client package not available")
        return get_neo4j_client()

    async def _run(self, cypher: str, params: dict | None = None):
        await self._client().execute_schema(cypher, params or {})

    # ── Domain ──

    async def _sync_domains(self):
        """Merkle Domain nodes with an ``fqn`` property so generic MATCH
        (``{fqn: …}``) works for relationships that target domains."""
        cypher = """
            UNWIND $batch AS d
            MERGE (n:Domain {code: d.code})
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
        await self._run(cypher, {"batch": batch})
        logger.info("Synced %d Domain nodes", len(batch))

    # ── Entity + auto IN_DOMAIN ──

    async def _sync_entities(self):
        cypher = """
            UNWIND $batch AS e
            CALL apoc.merge.node(
                [e.entity_type],
                {fqn: e.fqn},
                {
                    entity_type: e.entity_type,
                    name_cn: e.name_cn,
                    name_en: e.name_en,
                    src_tables: e.src_tables,
                    domains: e.domains,
                    description: e.description,
                    source: e.source,
                    status: e.status
                }
            ) YIELD node
            WITH node, e
            UNWIND e.domains AS dc
            MATCH (d:Domain {code: dc})
            MERGE (node)-[r:IN_DOMAIN]->(d)
            SET r.source = 'registry',
                r.status = 'active'
            RETURN count(DISTINCT node)
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
        await self._run(cypher, {"batch": batch})
        logger.info("Synced %d Entity nodes + auto IN_DOMAIN", len(batch))

    # ── Property + auto HAS_PROPERTY + IN_DOMAIN ──

    async def _sync_properties(self):
        cypher = """
            UNWIND $batch AS row
            MATCH (e {fqn: row.entity_fqn})
            WHERE e.entity_type IS NOT NULL
            MERGE (p:Property {fqn: row.fqn})
            SET p.name = row.name,
                p.data_type = row.data_type,
                p.is_pk = row.is_pk,
                p.is_fk = row.is_fk,
                p.ref_property_fqn = row.ref_property_fqn,
                p.description = row.description,
                p.name_cn = row.name_cn,
                p.name_en = row.name_en,
                p.source = row.source,
                p.status = row.status
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
            await self._run(cypher, {"batch": batch[i : i + self.BATCH_SIZE]})
        logger.info("Synced %d Property nodes + auto HAS_PROPERTY + IN_DOMAIN", len(batch))

    # ── Enrich entities with property-derived attributes ──

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
                "properties": properties,
            })

        cypher = """
            UNWIND $batch AS row
            MATCH (e {fqn: row.fqn})
            WHERE e.entity_type IS NOT NULL
            SET e.property_count = row.property_count,
                e.pk_properties = row.pk_properties,
                e.fk_properties = row.fk_properties,
                e.has_pk = row.has_pk,
                e.has_fk = row.has_fk,
                e.properties = row.properties
        """
        await self._run(cypher, {"batch": batch})
        logger.info("Enriched %d entity nodes with property-derived attributes", len(batch))

    # ── FK auto-creation from Property definitions ──

    async def _sync_fk_relationships(self):
        active_entity_fqns = {e.fqn for e in self.registry.entities if e.status == "active"}
        fk_properties = [
            p for p in self.registry.properties
            if p.is_fk and p.ref_property_fqn and p.entity_fqn in active_entity_fqns
        ]
        if not fk_properties:
            return
        cypher = """
            UNWIND $batch AS row
            MATCH (src:Property {fqn: row.src_fqn})
            MATCH (dst:Property {fqn: row.dst_fqn})
            MERGE (src)-[r:REFERENCES]->(dst)
            SET r.source = 'fk_introspect',
                r.status = 'active'
        """
        batch = [{"src_fqn": p.fqn, "dst_fqn": p.ref_property_fqn} for p in fk_properties]
        await self._run(cypher, {"batch": batch})
        logger.info("Auto-created %d FK relationships", len(batch))

    # ── Relationships from Relationship sheet (manual overrides) ──

    async def _sync_relationships(self):
        """Merge manually-defined relationships via ``apoc.merge.relationship``.

        Because this runs *after* auto-creation, any match on
        (src, rel_type, dst) will **update** the relationship properties
        (source, status, …) with the values from the Relationship sheet.
        """
        active_rels = [r for r in self.registry.relationships if r.status == "active"]
        if not active_rels:
            return

        cypher = """
            UNWIND $batch AS row
            MATCH (src {fqn: row.src_fqn})
            MATCH (dst {fqn: row.dst_fqn})
            CALL apoc.merge.relationship(
                src, row.rel_type, {}, {}, dst,
                {directed: row.directed}
            ) YIELD rel
            SET rel.source = row.source,
                rel.status = row.status
        """
        batch = [
            {
                "src_fqn": r.src_fqn,
                "dst_fqn": r.dst_fqn,
                "rel_type": r.rel_type,
                "directed": r.is_directed,
                "source": r.source,
                "status": r.status,
            }
            for r in active_rels
        ]
        for i in range(0, len(batch), self.BATCH_SIZE):
            await self._run(cypher, {"batch": batch[i : i + self.BATCH_SIZE]})
        logger.info("Merged %d manually-defined relationships (Relationship sheet)", len(batch))

    # ── Full sync ──

    async def sync_all(self):
        logger.info("Starting full graph sync ...")
        await self._sync_domains()
        await self._sync_entities()
        await self._sync_properties()
        await self._enrich_entities()
        await self._sync_fk_relationships()
        await self._sync_relationships()
        logger.info("Graph sync completed.")
