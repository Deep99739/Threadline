"""Local stdio runtime for the read-only Threadline MCP server."""

from __future__ import annotations

from pathlib import Path

from threadline.demo import (
    DEMO_ACTOR_ID,
    DEMO_REPOSITORY_ID,
    DEMO_TASK_ID,
    DEMO_TENANT_ID,
    DEMO_WORKSPACE_ID,
    default_demo_repository,
)
from threadline.mcp_server import create_mcp_server
from threadline.service import ServiceScope
from threadline.storage import ThreadlineStore
from threadline.workspace import load_local_workspace, workspace_database_url


def serve_demo_mcp(database_url: str) -> None:
    store = ThreadlineStore(database_url)
    try:
        scope = ServiceScope(
            tenant_id=DEMO_TENANT_ID,
            workspace_id=DEMO_WORKSPACE_ID,
            actor_id=DEMO_ACTOR_ID,
            repository_id=DEMO_REPOSITORY_ID,
        )
        create_mcp_server(
            store,
            scope,
            DEMO_TASK_ID,
            default_demo_repository(),
        ).run("stdio")
    finally:
        store.close()


def serve_workspace_mcp(repository_path: Path, database_url: str | None = None) -> None:
    """Expose an explicitly synchronized Git workspace through read-only scoped tools."""

    workspace = load_local_workspace(repository_path)
    resolved_database_url = workspace_database_url(workspace, database_url)
    store = ThreadlineStore(resolved_database_url)
    try:
        handoff = store.load_latest_handoff(
            tenant_id=workspace.scope.tenant_id,
            workspace_id=workspace.scope.workspace_id,
            task_id=workspace.manifest.task.id,
        )
        version = handoff.get("repository_version", {})
        if not isinstance(version, dict) or (
            version.get("branch") != workspace.git_snapshot.repository_version.branch
            or version.get("commit_sha") != workspace.git_snapshot.repository_version.commit_sha
        ):
            raise ValueError("compiled handoff is stale; run threadline sync first")
        create_mcp_server(
            store,
            workspace.scope,
            workspace.manifest.task.id,
            workspace.repository_path,
        ).run("stdio")
    finally:
        store.close()
