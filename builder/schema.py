from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

NT = "Entity"
NP = "Field"

_DDL_STATEMENTS: list[str] = [
    f"""CREATE NODE TABLE IF NOT EXISTS Domain(
        code STRING, fqn STRING, name_cn STRING, name_en STRING,
        parent_code STRING, description STRING, source STRING, status STRING,
        PRIMARY KEY (code)
    )""",
    f"""CREATE NODE TABLE IF NOT EXISTS {NT}(
        fqn STRING, entity_type STRING, name_cn STRING, name_en STRING,
        src_tables STRING[], domains STRING[], description STRING,
        source STRING, status STRING, property_count INT64,
        pk_properties STRING[], fk_properties STRING[],
        has_pk BOOLEAN, has_fk BOOLEAN, properties STRING,
        pagerank DOUBLE, betweenness DOUBLE, degree DOUBLE,
        community_id INT64, wcc_id INT64,
        PRIMARY KEY (fqn)
    )""",
    f"""CREATE NODE TABLE IF NOT EXISTS {NP}(
        fqn STRING, entity_fqn STRING, name STRING, data_type STRING,
        is_pk BOOLEAN, is_fk BOOLEAN, ref_property_fqn STRING,
        description STRING, name_cn STRING, name_en STRING,
        source STRING, status STRING, domains STRING[],
        pagerank DOUBLE, betweenness DOUBLE, degree DOUBLE,
        community_id INT64, wcc_id INT64,
        PRIMARY KEY (fqn)
    )""",
    f"""CREATE REL TABLE IF NOT EXISTS IN_DOMAIN(
        FROM {NT} TO Domain, source STRING, status STRING
    )""",
    f"""CREATE REL TABLE IF NOT EXISTS HAS_PROPERTY(
        FROM {NT} TO {NP}
    )""",
    f"""CREATE REL TABLE IF NOT EXISTS REFERENCES(
        FROM {NP} TO {NP}, source STRING, status STRING
    )""",
]


def ensure_schema(client: Any) -> None:
    """Create node / rel tables that need specific schemas."""
    for ddl in _DDL_STATEMENTS:
        try:
            client.execute(ddl)
        except Exception as e:
            logger.warning("DDL (may already exist): %s", e)
    logger.info("Kuzu schema ensured (core tables)")
