"""Local repository workspace lifecycle with deterministic, non-secret scope identifiers."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid5

from sqlalchemy.engine import make_url

from threadline.compiler import CompiledHandoff
from threadline.git_repository import GitSnapshot, read_git_snapshot, threadline_git_state_path
from threadline.manifest import (
    ProjectManifest,
    manifest_from_git_snapshot,
    read_worktree_manifest,
)
from threadline.migrations import upgrade_database
from threadline.service import ServiceScope, ThreadlineService
from threadline.storage import ThreadlineStore

LOCAL_SCOPE_NAMESPACE = UUID("35b2d830-32a7-4d41-878f-d6fe8f239ee0")


@dataclass(frozen=True)
class LocalWorkspace:
    repository_path: Path
    manifest: ProjectManifest
    git_snapshot: GitSnapshot
    scope: ServiceScope


@dataclass(frozen=True)
class WorkspaceSyncResult:
    workspace: LocalWorkspace
    database_url: str
    handoff: CompiledHandoff


def _scope(manifest: ProjectManifest) -> ServiceScope:
    repository_key = str(manifest.repository_id)
    return ServiceScope(
        tenant_id=uuid5(LOCAL_SCOPE_NAMESPACE, "local-tenant"),
        workspace_id=uuid5(LOCAL_SCOPE_NAMESPACE, f"workspace:{repository_key}"),
        actor_id=uuid5(LOCAL_SCOPE_NAMESPACE, f"local-actor:{repository_key}"),
        repository_id=manifest.repository_id,
    )


def load_local_workspace(repository_path: Path) -> LocalWorkspace:
    root, worktree_manifest = read_worktree_manifest(repository_path)
    snapshot = read_git_snapshot(root, worktree_manifest.repository_id)
    committed_manifest = manifest_from_git_snapshot(snapshot)
    if committed_manifest != worktree_manifest:
        raise ValueError(
            "threadline.json has uncommitted changes; commit or revert it before syncing context"
        )
    return LocalWorkspace(
        repository_path=root,
        manifest=committed_manifest,
        git_snapshot=snapshot,
        scope=_scope(committed_manifest),
    )


def workspace_database_url(workspace: LocalWorkspace, explicit: str | None = None) -> str:
    if explicit is not None:
        return explicit
    configured = os.getenv("THREADLINE_DATABASE_URL")
    if configured:
        return configured
    database_path = threadline_git_state_path(workspace.repository_path)
    return f"sqlite+pysqlite:///{database_path}"


def sync_local_workspace(
    repository_path: Path,
    *,
    database_url: str | None = None,
    query: str | None = None,
) -> WorkspaceSyncResult:
    workspace = load_local_workspace(repository_path)
    resolved_database_url = workspace_database_url(workspace, database_url)
    if resolved_database_url.startswith("sqlite"):
        database_name = make_url(resolved_database_url).database
        if database_name and database_name != ":memory:":
            Path(database_name).parent.mkdir(parents=True, exist_ok=True)
    upgrade_database(resolved_database_url)
    store = ThreadlineStore(resolved_database_url)
    try:
        service = ThreadlineService(store)
        service.ingest(repository_path=workspace.repository_path, scope=workspace.scope)
        handoff = service.compile_task_handoff(
            scope=workspace.scope,
            task_id=workspace.manifest.task.id,
            query=query or workspace.manifest.task.query,
        )
        return WorkspaceSyncResult(
            workspace=workspace,
            database_url=resolved_database_url,
            handoff=handoff,
        )
    finally:
        store.close()
