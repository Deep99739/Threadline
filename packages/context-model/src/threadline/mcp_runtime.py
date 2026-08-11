"""Local stdio runtime for the read-only Threadline MCP server."""

from __future__ import annotations

from pathlib import Path

from threadline.demo import (
    DEMO_ACTOR_ID,
    DEMO_REPOSITORY_ID,
    DEMO_TENANT_ID,
    DEMO_WORKSPACE_ID,
)
from threadline.mcp_server import create_mcp_server
from threadline.service import ServiceScope
from threadline.storage import ThreadlineStore
from threadline.workspace import sync_local_workspace


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


def serve_workspace_mcp(repository_path: Path, database_url: str | None = None) -> None:
    """Synchronize one exact Git workspace, then expose only read-only scoped tools."""

    synced = sync_local_workspace(repository_path, database_url=database_url)
    store = ThreadlineStore(synced.database_url)
    try:
        create_mcp_server(store, synced.workspace.scope).run("stdio")
    finally:
        store.close()
