import logging

try:
    from neo4j_client import Neo4jClientError, get_neo4j_client
except ImportError:
    get_neo4j_client = None
    Neo4jClientError = Exception

from registry.models import RegistryData

logger = logging.getLogger(__name__)


class GraphBuilder:
    """Project RegistryData onto Neo4j via idempotent MERGE."""

    BATCH_SIZE = 500

    def __init__(self, registry: RegistryData):
        self.registry = registry

    def _client(self):
        if get_neo4j_client is None:
            raise RuntimeError("neo4j-client package not available")
        return get_neo4j_client()

    def _run(self, cypher: str, params: dict | None = None):
        self._client().execute_schema(cypher, params or {})

    # ── Domain ──

    def _sync_domains(self):
        cypher = """
            UNWIND $batch AS d
            MERGE (n:Domain {code: d.code})
            SET n.name = d.name,
                n.parent_code = d.parent_code,
                n.description = d.description,
                n.source = d.source
        """
        batch = [
            {
                "code": d.code,
                "name": d.name,
                "parent_code": d.parent_code or "",
                "description": d.description,
                "source": d.source,
            }
            for d in self.registry.domains
        ]
        self._run(cypher, {"batch": batch})
        logger.info("Synced %d Domain nodes", len(batch))

    # ── Table ──

    def _sync_tables(self):
        cypher = """
            UNWIND $batch AS t
            MERGE (n:Table {fqn: t.fqn})
            SET n.name = t.name,
                n.schema_name = t.schema_name,
                n.type = t.type,
                n.business_object = t.business_object,
                n.domains = t.domains,
                n.comment = t.comment,
                n.status = t.status
        """
        batch = [
            {
                "fqn": t.fqn,
                "name": t.table_name,
                "schema_name": t.schema_name,
                "type": t.type,
                "business_object": t.business_object,
                "domains": t.domains,
                "comment": t.comment,
                "status": t.status,
            }
            for t in self.registry.tables
        ]
        self._run(cypher, {"batch": batch})
        logger.info("Synced %d Table nodes", len(batch))

    # ── Column + HAS_COLUMN + IN_DOMAIN ──

    def _sync_columns(self):
        cypher = """
            UNWIND $batch AS row
            MATCH (t:Table {fqn: row.table_fqn})
            MERGE (c:Column {fqn: row.fqn})
            SET c.name = row.name,
                c.data_type = row.data_type,
                c.nullable = row.nullable,
                c.is_pk = row.is_pk,
                c.is_fk = row.is_fk,
                c.ref_column_fqn = row.ref_column_fqn,
                c.semantic_type = row.semantic_type,
                c.domains = row.domains,
                c.comment = row.comment
            MERGE (t)-[:HAS_COLUMN]->(c)
            WITH c, row
            UNWIND row.domains AS dc
            MATCH (d:Domain {code: dc})
            MERGE (c)-[r:IN_DOMAIN]->(d)
            SET r.source = 'registry'
        """
        batch = [
            {
                "fqn": c.fqn,
                "table_fqn": c.table_fqn,
                "name": c.name,
                "data_type": c.data_type,
                "nullable": c.nullable,
                "is_pk": c.is_pk,
                "is_fk": c.is_fk,
                "ref_column_fqn": c.ref_column_fqn or "",
                "semantic_type": c.semantic_type,
                "domains": c.domains,
                "comment": c.comment,
            }
            for c in self.registry.columns
        ]
        # Neo4j may throttle large UNWIND, split into batches
        for i in range(0, len(batch), self.BATCH_SIZE):
            self._run(cypher, {"batch": batch[i : i + self.BATCH_SIZE]})
        logger.info("Synced %d Column nodes + HAS_COLUMN + IN_DOMAIN", len(batch))

    # ── Relationships ──

    def _sync_relationships(self):
        column_rels = [r for r in self.registry.relationships if r.node_level == "column"]
        if not column_rels:
            return

        cypher = """
            UNWIND $batch AS row
            MATCH (src:Column {fqn: row.src_fqn})
            MATCH (dst:Column {fqn: row.dst_fqn})
            CALL apoc.create.relationship(src, row.rel_type, row.props, dst) YIELD rel
            SET rel.source = row.source,
                rel.status = row.status
            RETURN count(*)
        """
        batch = [
            {
                "src_fqn": r.src_fqn,
                "dst_fqn": r.dst_fqn,
                "rel_type": r.rel_type,
                "props": r.properties,
                "source": r.source,
                "status": r.status,
            }
            for r in column_rels
        ]
        for i in range(0, len(batch), self.BATCH_SIZE):
            self._run(cypher, {"batch": batch[i : i + self.BATCH_SIZE]})
        logger.info("Synced %d relationships", len(batch))

    # ── Full sync ──

    def sync_all(self):
        logger.info("Starting full graph sync ...")
        self._sync_domains()
        self._sync_tables()
        self._sync_columns()
        self._sync_relationships()
        logger.info("Graph sync completed.")
