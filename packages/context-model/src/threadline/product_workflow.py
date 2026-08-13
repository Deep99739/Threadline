"""Human-facing local workflows built on Threadline's exact-commit trust boundary."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from threadline.client_profiles import connect_client
from threadline.git_hooks import install_refresh_hooks
from threadline.git_repository import (
    commit_exact_paths,
    read_git_working_state,
    read_worktree_dirty_paths,
    resolve_git_root,
)
from threadline.manifest import (
    MANIFEST_PATH,
    ProjectManifest,
    initialize_manifest,
    read_worktree_manifest,
)
from threadline.storage import ThreadlineStore
from threadline.workspace import (
    load_local_workspace,
    sync_local_workspace,
    workspace_database_url,
)


def _check(code: str, status: str, detail: str) -> dict[str, str]:
    return {"code": code, "status": status, "detail": detail}


def onboard_workspace(
    repository_path: Path,
    *,
    objective: str,
    next_action: str,
    client: str,
    python_executable: Path | None = None,
) -> dict[str, Any]:
    """Create the contract, compile context, and connect one client in one safe command."""

    root = resolve_git_root(repository_path)
    dirty_paths = read_worktree_dirty_paths(root)
    if dirty_paths:
        raise ValueError(
            "onboarding requires a clean working tree; commit or revert: "
            + ", ".join(dirty_paths)
        )

    manifest_path = root / MANIFEST_PATH
    created_manifest_commit: str | None = None
    if manifest_path.exists():
        _existing_root, manifest = read_worktree_manifest(root)
        if manifest.task.objective != objective or manifest.task.next_action != next_action:
            raise ValueError(
                "threadline.json already defines a different task; use checkpoint to change it"
            )
    else:
        _path, manifest = initialize_manifest(
            root,
            objective=objective,
            next_action=next_action,
        )
        created_manifest_commit = commit_exact_paths(
            root,
            (MANIFEST_PATH,),
            "Add Threadline context",
        )

    synced = sync_local_workspace(root)
    connection = connect_client(
        root,
        client,
        python_executable=python_executable,
    )
    hooks = install_refresh_hooks(
        root,
        python_executable=python_executable,
    )
    report = inspect_workspace(root)
    if not report["ready"]:
        raise RuntimeError("onboarding did not produce a current trusted handoff")
    return {
        "ready": True,
        "repository": str(root),
        "task_id": str(manifest.task.id),
        "commit_created": created_manifest_commit,
        "context_commit": synced.handoff.context_pack.repository_version.commit_sha,
        "client": connection,
        "refresh_hooks": hooks,
        "requires_api_key": False,
        "first_action": f"Open {client} in this repository and ask for Threadline status.",
    }


def inspect_workspace(repository_path: Path) -> dict[str, Any]:
    """Return actionable local readiness without mutating repository or database state."""

    checks: list[dict[str, str]] = []
    try:
        workspace = load_local_workspace(repository_path)
    except (FileNotFoundError, ValueError, ValidationError) as error:
        return {
            "ready": False,
            "requires_api_key": False,
            "checks": [_check("manifest", "failed", str(error))],
            "next_command": "threadline init . --objective ... --next-action ...",
        }

    live = read_git_working_state(workspace.repository_path, workspace.scope.repository_id)
    checks.append(
        _check(
            "manifest",
            "passed",
            "threadline.json is valid and matches the committed Git snapshot",
        )
    )
    if live.dirty_paths:
        checks.append(
            _check(
                "working_tree",
                "failed",
                f"uncommitted paths: {', '.join(live.dirty_paths)}",
            )
        )
    else:
        checks.append(_check("working_tree", "passed", "working tree is clean"))

    database_url = workspace_database_url(workspace)
    handoff: dict[str, Any] | None = None
    database_name = make_url(database_url).database
    database_missing = (
        database_url.startswith("sqlite")
        and database_name not in {None, ":memory:"}
        and not Path(str(database_name)).is_file()
    )
    if not database_missing:
        try:
            store = ThreadlineStore(database_url)
            try:
                handoff = store.load_latest_handoff(
                    tenant_id=workspace.scope.tenant_id,
                    workspace_id=workspace.scope.workspace_id,
                    task_id=workspace.manifest.task.id,
                )
            finally:
                store.close()
        except (LookupError, OSError, SQLAlchemyError):
            handoff = None
    if handoff is None:
        checks.append(
            _check(
                "sync_required",
                "failed",
                "no compiled handoff exists for this repository",
            )
        )

    handoff_current = False
    if handoff is not None:
        raw_version = handoff.get("repository_version", {})
        handoff_commit = raw_version.get("commit_sha") if isinstance(raw_version, dict) else None
        handoff_branch = raw_version.get("branch") if isinstance(raw_version, dict) else None
        handoff_current = (
            handoff_branch == live.repository_version.branch
            and handoff_commit == live.repository_version.commit_sha
            and not live.dirty_paths
        )
        checks.append(
            _check(
                "handoff",
                "passed" if handoff_current else "failed",
                (
                    "compiled handoff matches the exact clean repository commit"
                    if handoff_current
                    else "compiled handoff is stale or the working tree is dirty"
                ),
            )
        )

    ready = handoff_current and all(item["status"] == "passed" for item in checks)
    return {
        "ready": ready,
        "requires_api_key": False,
        "repository": {
            "path": str(workspace.repository_path),
            "branch": live.repository_version.branch,
            "commit": live.repository_version.commit_sha,
            "dirty_paths": list(live.dirty_paths),
        },
        "task": {
            "id": str(workspace.manifest.task.id),
            "objective": workspace.manifest.task.objective,
            "next_action": workspace.manifest.task.next_action,
        },
        "handoff": {"current": handoff_current},
        "checks": checks,
        "next_command": (
            f"threadline handoff {workspace.repository_path}"
            if ready
            else f"threadline sync {workspace.repository_path}"
        ),
    }


def checkpoint_workspace(
    repository_path: Path,
    *,
    statement: str,
    next_action: str,
    actor: str = "AGENT",
) -> dict[str, Any]:
    """Stage a reviewable asserted observation in the committed project contract."""

    root, current = read_worktree_manifest(repository_path)
    live = read_git_working_state(root, current.repository_id)
    if "threadline.json" in live.dirty_paths:
        raise ValueError(
            "threadline.json already has uncommitted changes; review, commit, or revert "
            "them before adding another checkpoint"
        )
    if actor not in {"AGENT", "HUMAN"}:
        raise ValueError("checkpoint actor must be AGENT or HUMAN")

    payload = current.model_dump(mode="json")
    payload["task"]["next_action"] = next_action
    payload["task"]["query"] = f"{current.task.objective} {next_action}"
    payload["observations"].append(
        {
            "actor_type": actor,
            "statement": statement,
            "state": "ASSERTED",
            "source_path": "threadline.json",
        }
    )
    updated = ProjectManifest.model_validate(payload)
    manifest_path = root / "threadline.json"
    manifest_path.write_text(
        json.dumps(updated.model_dump(mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "manifest": str(manifest_path),
        "task_id": str(updated.task.id),
        "epistemic_state": "ASSERTED",
        "statement": statement,
        "next_action": next_action,
        "worktree_paths_to_commit_together": [
            *live.dirty_paths,
            "threadline.json",
        ],
        "next": (
            "Review the manifest diff, commit it with the work it describes in one commit, "
            "then run "
            f"threadline sync {root}."
        ),
    }


def handoff_content(repository_path: Path, *, database_url: str | None = None) -> dict[str, Any]:
    """Return an already-compiled exact-commit handoff without mutating stored context."""

    workspace = load_local_workspace(repository_path)
    live = read_git_working_state(workspace.repository_path, workspace.scope.repository_id)
    if live.dirty_paths:
        raise ValueError(
            "working tree is dirty; commit or revert changes before reading verified context"
        )
    resolved_database_url = workspace_database_url(workspace, database_url)
    database_name = make_url(resolved_database_url).database
    if (
        resolved_database_url.startswith("sqlite")
        and database_name not in {None, ":memory:"}
        and not Path(str(database_name)).is_file()
    ):
        raise LookupError("no compiled handoff exists; run threadline sync first")
    store = ThreadlineStore(resolved_database_url)
    try:
        content = store.load_latest_handoff(
            tenant_id=workspace.scope.tenant_id,
            workspace_id=workspace.scope.workspace_id,
            task_id=workspace.manifest.task.id,
        )
    finally:
        store.close()
    version = content.get("repository_version", {})
    if not isinstance(version, dict) or (
        version.get("branch") != live.repository_version.branch
        or version.get("commit_sha") != live.repository_version.commit_sha
    ):
        raise ValueError("compiled handoff is stale; run threadline sync first")
    return content


def render_handoff_markdown(content: dict[str, Any]) -> str:
    """Render a compact, model-neutral handoff with evidence URIs."""

    version = content.get("repository_version", {})
    pack = content.get("context_pack", {})
    items = pack.get("items", []) if isinstance(pack, dict) else []
    lines = [
        "# Threadline handoff",
        "",
        f"Repository: `{version.get('branch')}@{version.get('commit_sha')}`",
        "",
        "## Objective",
        "",
        str(content.get("objective", "")),
        "",
        "## Next action",
        "",
        str(content.get("next_action", "")),
    ]
    for title, key in (
        ("Constraints", "constraints"),
        ("Verified completed work", "verified_completed_work"),
        ("Contradictions", "contradictions"),
        ("Unknowns", "unknowns"),
    ):
        values = content.get(key, [])
        lines.extend(["", f"## {title}", ""])
        lines.extend(f"- {value}" for value in values) if values else lines.append("- None")

    lines.extend(["", "## Evidence-backed context", ""])
    for item in items:
        if not isinstance(item, dict):
            continue
        lines.append(f"- [{item.get('epistemic_state', 'UNKNOWN')}] {item.get('statement', '')}")
        citations = item.get("citations", [])
        if isinstance(citations, list):
            for citation in citations:
                locator = citation.get("locator", {}) if isinstance(citation, dict) else {}
                if isinstance(locator, dict) and locator.get("uri"):
                    lines.append(f"  - {locator['uri']} ({locator.get('content_hash', '')})")
    return "\n".join(lines).rstrip() + "\n"
