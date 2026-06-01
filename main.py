"""Assistant20 Tools - Kuzu Graph Database Query Tools Service.

This service provides tools for querying Kuzu graph database
and PostgreSQL database, including schema search, subgraph fetch,
lineage trace, join path discovery, SQL execution, risk check, and graph insights.
"""

import logging
from pathlib import Path

from dotenv import load_dotenv
from mh_service_kit import ServiceApp
from minimal_harness.client.logging_setup import setup_service_logging

load_dotenv(Path(__file__).parent / ".env")

from kuzu_client import close_kuzu_client, get_kuzu_client
from pg_client import close_pg_client
from tools.insight_tools.graph_insight import TOOL as GRAPH_INSIGHT_TOOL
from tools.insight_tools.graph_insight import execute as graph_insight_execute
from tools.insight_tools.risk_check import TOOL as RISK_CHECK_INSIGHT_TOOL
from tools.insight_tools.risk_check import execute as risk_check_insight_execute
from tools.query_schema_data import TOOL as QUERY_SCHEMA_DATA_TOOL
from tools.query_schema_data import execute as query_schema_data_execute
from tools.query_schema_props import TOOL as QUERY_SCHEMA_PROPS_TOOL
from tools.query_schema_props import execute as query_schema_props_execute
from tools.query_schema_rels import TOOL as QUERY_SCHEMA_RELS_TOOL
from tools.query_schema_rels import execute as query_schema_rels_execute
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

# Eagerly initialize Kuzu client on service startup
try:
    get_kuzu_client()
    logger.info("Kuzu client initialized on startup")
except Exception:
    logger.warning("Kuzu client initialization on startup failed, will retry on first request")


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

    # Register schema query tools
    service.add_tool(**QUERY_SCHEMA_DATA_TOOL, handler=query_schema_data_execute)
    service.add_tool(**QUERY_SCHEMA_PROPS_TOOL, handler=query_schema_props_execute)
    service.add_tool(**QUERY_SCHEMA_RELS_TOOL, handler=query_schema_rels_execute)

    # Register insight tools
    service.add_tool(**RISK_CHECK_INSIGHT_TOOL, handler=risk_check_insight_execute)
    service.add_tool(**GRAPH_INSIGHT_TOOL, handler=graph_insight_execute)

    logger.info("All 10 tools registered successfully")
    return service


# Create the service instance
service = create_service()

# Build the FastAPI app
app = service.build()


async def shutdown() -> None:
    """Shutdown handler to close database client connections."""
    await close_kuzu_client()
    await close_pg_client()
    logger.info("All database client connections closed")


def main() -> None:
    """Main entry point for running the service."""
    service.run(host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
