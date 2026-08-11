"""Local stdio runtime for the read-only Threadline MCP server."""

from __future__ import annotations

from threadline.demo import (
    DEMO_ACTOR_ID,
    DEMO_REPOSITORY_ID,
    DEMO_TENANT_ID,
    DEMO_WORKSPACE_ID,
)
from threadline.mcp_server import create_mcp_server
from threadline.service import ServiceScope
from threadline.storage import ThreadlineStore


def serve_demo_mcp(database_url: str) -> None:
    store = ThreadlineStore(database_url)
    try:
        scope = ServiceScope(
            tenant_id=DEMO_TENANT_ID,
            workspace_id=DEMO_WORKSPACE_ID,
            actor_id=DEMO_ACTOR_ID,
            repository_id=DEMO_REPOSITORY_ID,
        )
        create_mcp_server(store, scope).run("stdio")
    finally:
        store.close()
