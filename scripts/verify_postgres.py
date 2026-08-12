"""Prove Threadline's migrated PostgreSQL path with an isolated real database."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url

from threadline.manifest import ProjectManifest
from threadline.migrations import upgrade_database
from threadline.service import ServiceScope, ThreadlineService
from threadline.storage import ThreadlineStore

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ADMIN_URL = (
    "postgresql+psycopg://threadline:threadline_local@localhost:55432/postgres"
)


def _git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.stdout.strip()


def _make_repository(parent: Path) -> Path:
    repository = parent / "postgres-proof-repository"
    shutil.copytree(ROOT / "demo" / "synthetic-repo", repository)
    _git(repository, "init", "-b", "postgres-proof")
    _git(repository, "add", ".")
    _git(
        repository,
        "-c",
        "user.name=Threadline PostgreSQL Proof",
        "-c",
        "user.email=postgres-proof@example.invalid",
        "commit",
        "-m",
        "Create PostgreSQL proof repository",
    )
    return repository


def _database_url(admin_url: URL, database_name: str) -> str:
    return admin_url.set(database=database_name).render_as_string(hide_password=False)


def main() -> None:
    admin_url = make_url(os.getenv("THREADLINE_POSTGRES_ADMIN_URL", DEFAULT_ADMIN_URL))
    database_name = f"threadline_verify_{uuid4().hex[:16]}"
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    store: ThreadlineStore | None = None

    try:
        with admin_engine.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{database_name}"'))

        database_url = _database_url(admin_url, database_name)
        upgrade_database(database_url)
        store = ThreadlineStore(database_url)
        service = ThreadlineService(store)
        scope = ServiceScope(
            tenant_id=uuid4(),
            workspace_id=uuid4(),
            actor_id=uuid4(),
            repository_id=uuid4(),
        )

        with tempfile.TemporaryDirectory(prefix="threadline-postgres-") as directory:
            repository = _make_repository(Path(directory))
            manifest = ProjectManifest.model_validate_json(
                (repository / "threadline.json").read_text(encoding="utf-8")
            )
            scope = ServiceScope(
                tenant_id=scope.tenant_id,
                workspace_id=scope.workspace_id,
                actor_id=scope.actor_id,
                repository_id=manifest.repository_id,
            )
            ingestion = service.ingest(repository_path=repository, scope=scope)
            compiled = service.compile_task_handoff(
                scope=scope,
                task_id=ingestion.snapshot.task.id,
                query="continue retry work without duplicate side effects",
            )

        if not compiled.context_pack.items:
            raise AssertionError("PostgreSQL handoff did not retain context items")
        if not any(item.citations for item in compiled.context_pack.items):
            raise AssertionError("PostgreSQL handoff did not retain citations")

        try:
            store.load_snapshot(
                tenant_id=uuid4(),
                workspace_id=scope.workspace_id,
                task_id=ingestion.snapshot.task.id,
            )
        except LookupError:
            pass
        else:
            raise AssertionError("PostgreSQL storage allowed a cross-tenant read")

        store.close()
        store = ThreadlineStore(database_url)
        persisted = service.__class__(store).latest_handoff(
            scope=scope,
            task_id=ingestion.snapshot.task.id,
        )
        if persisted != compiled.content:
            raise AssertionError("PostgreSQL handoff did not survive a new connection")

        print(
            json.dumps(
                {
                    "database": "isolated temporary PostgreSQL database",
                    "migration": "head",
                    "ingestion": "passed",
                    "cited_handoff": "passed",
                    "cross_tenant_read": "rejected",
                    "reconnection": "passed",
                },
                indent=2,
            )
        )
    finally:
        if store is not None:
            store.close()
        with admin_engine.connect() as connection:
            connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :database_name AND pid <> pg_backend_pid()"
                ),
                {"database_name": database_name},
            )
            connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}"'))
        admin_engine.dispose()


if __name__ == "__main__":
    main()
