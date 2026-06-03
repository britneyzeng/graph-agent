from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

NT = "Entity"
NP = "Field"
NL = "Logic"

_DDL_STATEMENTS: list[str] = [
    # Node tables
    """CREATE NODE TABLE IF NOT EXISTS Domain(
        fqn STRING, name_cn STRING, name_en STRING,
        parent_fqn STRING, description STRING, source STRING, status STRING,
        PRIMARY KEY (fqn)
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
        is_pk BOOLEAN, ref_property_fqn STRING,
        description STRING, name_cn STRING, name_en STRING,
        source STRING, status STRING, domains STRING[],
        pagerank DOUBLE, betweenness DOUBLE, degree DOUBLE,
        community_id INT64, wcc_id INT64,
        PRIMARY KEY (fqn)
    )""",
    f"""CREATE NODE TABLE IF NOT EXISTS {NL}(
        fqn STRING, logic_type STRING, expression STRING,
        name_cn STRING, name_en STRING, description STRING,
        source STRING, status STRING,
        PRIMARY KEY (fqn)
    )""",
    # Relationship tables
    f"""CREATE REL TABLE IF NOT EXISTS IN_DOMAIN(
        FROM {NT} TO Domain, source STRING, status STRING
    )""",
    f"""CREATE REL TABLE IF NOT EXISTS HAS_PROPERTY(
        FROM {NT} TO {NP}, source STRING, status STRING
    )""",
    f"""CREATE REL TABLE IF NOT EXISTS COMPUTES(
        FROM {NL} TO {NP}, source STRING, status STRING
    )""",
    f"""CREATE REL TABLE IF NOT EXISTS LOGIC_LINK(
        FROM {NL} TO {NL}, source STRING, status STRING
    )""",
    f"""CREATE REL TABLE IF NOT EXISTS FIELD_LINK(
        FROM {NP} TO {NP}, source STRING, status STRING
    )""",
    f"""CREATE REL TABLE IF NOT EXISTS ENTITY_LINK(
        FROM {NT} TO {NT}, source STRING, status STRING
    )""",
    """CREATE REL TABLE IF NOT EXISTS DOMAIN_LINK(
        FROM Domain TO Domain, source STRING, status STRING
    )""",
    f"""CREATE REL TABLE IF NOT EXISTS USE_LOGIC(
        FROM {NT} TO {NL}, source STRING, status STRING
    )""",
    f"""CREATE REL TABLE IF NOT EXISTS HAS_LOGIC(
        FROM Domain TO {NL}, source STRING, status STRING
    )""",
]


def ensure_schema(client: Any) -> None:
    for ddl in _DDL_STATEMENTS:
        try:
            client.execute(ddl)
        except Exception as e:
            logger.warning("DDL (may already exist): %s", e)
    logger.info("Kuzu schema ensured (9 rel tables, 4 node tables)")
