"""Repeatable synthetic continuation demo backed only by real product behavior."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from threadline.compiler import CompiledHandoff
from threadline.migrations import project_root, upgrade_database
from threadline.service import ServiceScope, ThreadlineService
from threadline.storage import ThreadlineStore

DEMO_TENANT_ID = UUID("60000000-0000-4000-8000-000000000001")
DEMO_WORKSPACE_ID = UUID("60000000-0000-4000-8000-000000000002")
DEMO_ACTOR_ID = UUID("60000000-0000-4000-8000-000000000003")
DEMO_REPOSITORY_ID = UUID("60000000-0000-4000-8000-000000000004")
DEMO_TASK_ID = UUID("20000000-0000-4000-8000-000000000001")


@dataclass(frozen=True)
class DemoResult:
    repository_path: Path
    handoff: CompiledHandoff


def default_demo_repository() -> Path:
    return project_root() / ".threadline" / "demo-repository"


def _git(root: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )


def prepare_demo_repository(destination: Path) -> Path:
    destination = destination.resolve()
    if destination.exists():
        if (destination / ".git").is_dir():
            return destination
        raise FileExistsError(
            f"demo destination already exists and is not a Git repository: {destination}"
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(project_root() / "demo" / "synthetic-repo", destination)
    _git(destination, "init", "-b", "feature/retry-jobs")
    _git(destination, "add", ".")
    _git(
        destination,
        "-c",
        "user.name=Threadline Demo",
        "-c",
        "user.email=threadline-demo@example.invalid",
        "commit",
        "-m",
        "Create unfinished retry task",
    )
    return destination


def run_demo(database_url: str, repository_path: Path | None = None) -> DemoResult:
    path = prepare_demo_repository(repository_path or default_demo_repository())
    upgrade_database(database_url)
    store = ThreadlineStore(database_url)
    try:
        store.reset_tenant_for_demo(DEMO_TENANT_ID)
        service = ThreadlineService(store)
        scope = ServiceScope(
            tenant_id=DEMO_TENANT_ID,
            workspace_id=DEMO_WORKSPACE_ID,
            actor_id=DEMO_ACTOR_ID,
            repository_id=DEMO_REPOSITORY_ID,
        )
        service.ingest(repository_path=path, scope=scope)
        handoff = service.compile_task_handoff(
            scope=scope,
            task_id=DEMO_TASK_ID,
            query="continue retry work without duplicate side effects",
        )
        return DemoResult(repository_path=path, handoff=handoff)
    finally:
        store.close()
