"""Local repository workspace lifecycle with deterministic, non-secret scope identifiers."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid5

from sqlalchemy.engine import make_url

from threadline.compiler import CompiledHandoff
from threadline.git_repository import (
    GitRepositoryError,
    GitSnapshot,
    read_git_file,
    read_git_working_state,
    threadline_git_cache_path,
    threadline_git_state_path,
)
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
    working = read_git_working_state(root, worktree_manifest.repository_id)
    try:
        manifest_file = read_git_file(
            root,
            commit_sha=working.repository_version.commit_sha,
            relative_path="threadline.json",
        )
    except GitRepositoryError as error:
        raise ValueError(
            f"threadline.json is not committed at {working.repository_version.commit_sha}"
        ) from error
    snapshot = GitSnapshot(
        root=root,
        name=root.name,
        repository_version=working.repository_version,
        files=(manifest_file,),
    )
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
    progress: Callable[[str], None] | None = None,
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
        requested_query = query or workspace.manifest.task.query
        if query is None:
            try:
                existing = store.load_latest_compiled_handoff(
                    tenant_id=workspace.scope.tenant_id,
                    workspace_id=workspace.scope.workspace_id,
                    task_id=workspace.manifest.task.id,
                )
            except LookupError:
                existing = None
            if (
                existing is not None
                and existing.context_pack.repository_version
                == workspace.git_snapshot.repository_version
                and existing.content.get("query") == requested_query
            ):
                if progress is not None:
                    progress("Reused the current exact-commit handoff.")
                return WorkspaceSyncResult(
                    workspace=workspace,
                    database_url=resolved_database_url,
                    handoff=existing,
                )
        service.ingest(
            repository_path=workspace.repository_path,
            scope=workspace.scope,
            code_cache_path=threadline_git_cache_path(workspace.repository_path),
            replace_current_snapshot=resolved_database_url.startswith("sqlite"),
            progress=progress,
        )
        if progress is not None:
            progress("Compiling the evidence-bound handoff.")
        handoff = service.compile_task_handoff(
            scope=workspace.scope,
            task_id=workspace.manifest.task.id,
            query=requested_query,
        )
        if resolved_database_url.startswith("sqlite"):
            store.prune_task_history(
                tenant_id=workspace.scope.tenant_id,
                workspace_id=workspace.scope.workspace_id,
                task_id=workspace.manifest.task.id,
            )
        return WorkspaceSyncResult(
            workspace=workspace,
            database_url=resolved_database_url,
            handoff=handoff,
        )
    finally:
        store.close()
