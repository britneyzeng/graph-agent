"""Assistant20 Tools - Neo4j Graph Database Query Tools Service.

This service provides tools for querying Neo4j graph database
and PostgreSQL database, including schema search, subgraph fetch,
lineage trace, join path discovery, SQL execution, risk check, and graph insights.
"""

import logging

from mh_service_kit import ServiceApp
from minimal_harness.client.logging_setup import setup_service_logging

from neo4j_client import close_neo4j_client
from pg_client import close_pg_client
from tools.insight_tools.graph_insight import TOOL as GRAPH_INSIGHT_TOOL
from tools.insight_tools.graph_insight import execute as graph_insight_execute
from tools.insight_tools.risk_check import TOOL as RISK_CHECK_INSIGHT_TOOL
from tools.insight_tools.risk_check import execute as risk_check_insight_execute
from tools.query_tools.join_path_find import TOOL as JOIN_PATH_FIND_TOOL
from tools.query_tools.join_path_find import execute as join_path_find_execute
from tools.query_tools.lineage_trace import TOOL as LINEAGE_TRACE_TOOL
from tools.query_tools.lineage_trace import execute as lineage_trace_execute
from tools.query_tools.schema_search import TOOL as SCHEMA_SEARCH_TOOL
from tools.query_tools.schema_search import execute as schema_search_execute
from tools.query_tools.sql_executor import TOOL as SQL_EXECUTOR_TOOL
from tools.query_tools.sql_executor import execute as sql_executor_execute
from tools.query_tools.subgraph_fetch import TOOL as SUBGRAPH_FETCH_TOOL
from tools.query_tools.subgraph_fetch import execute as subgraph_fetch_execute

# Setup logging
setup_service_logging()
logger = logging.getLogger(__name__)


def create_service() -> ServiceApp:
    """Create and configure the assistant20-tools service."""
    service = ServiceApp(
        title="Assistant20 Tools",
        version="0.2.0",
        cors_origins=["http://localhost:5173", "http://localhost:3000"],
        default_locale="zh",
        dev_mode=True,
    )

    # Register query tools
    service.add_tool(**SCHEMA_SEARCH_TOOL, handler=schema_search_execute)
    service.add_tool(**SUBGRAPH_FETCH_TOOL, handler=subgraph_fetch_execute)
    service.add_tool(**LINEAGE_TRACE_TOOL, handler=lineage_trace_execute)
    service.add_tool(**JOIN_PATH_FIND_TOOL, handler=join_path_find_execute)
    service.add_tool(**SQL_EXECUTOR_TOOL, handler=sql_executor_execute)

    # Register insight tools
    service.add_tool(**RISK_CHECK_INSIGHT_TOOL, handler=risk_check_insight_execute)
    service.add_tool(**GRAPH_INSIGHT_TOOL, handler=graph_insight_execute)

    logger.info("All 7 tools registered successfully")
    return service


# Create the service instance
service = create_service()

# Build the FastAPI app
app = service.build()


async def shutdown() -> None:
    """Shutdown handler to close database client connections."""
    await close_neo4j_client()
    await close_pg_client()
    logger.info("All database client connections closed")


def main() -> None:
    """Main entry point for running the service."""
    service.run(host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
