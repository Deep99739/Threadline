"""Command-line entry point for Threadline's local vertical slice."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
from pathlib import Path

import uvicorn

from threadline.api import create_app
from threadline.client_profiles import build_client_profiles
from threadline.demo import default_demo_repository, prepare_demo_repository, run_demo
from threadline.manifest import initialize_manifest
from threadline.mcp_runtime import serve_demo_mcp, serve_workspace_mcp
from threadline.migrations import upgrade_database
from threadline.workspace import sync_local_workspace

DEFAULT_DATABASE_URL = "postgresql+psycopg://threadline:threadline_local@localhost:55432/threadline"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="threadline")
    subparsers = parser.add_subparsers(dest="command", required=True)

    migrate = subparsers.add_parser("migrate", help="apply explicit schema migrations")
    migrate.add_argument("--database-url")

    init = subparsers.add_parser(
        "init", help="create a repository-owned Threadline manifest"
    )
    init.add_argument("repository", nargs="?", type=Path, default=Path.cwd())
    init.add_argument("--objective", required=True)
    init.add_argument("--next-action", required=True)

    sync = subparsers.add_parser(
        "sync", help="ingest and compile the exact committed repository state"
    )
    sync.add_argument("repository", nargs="?", type=Path, default=Path.cwd())
    sync.add_argument("--database-url")
    sync.add_argument("--query")

    clients = subparsers.add_parser(
        "clients", help="print project-scoped MCP profiles without writing client settings"
    )
    clients.add_argument("repository", nargs="?", type=Path, default=Path.cwd())
    clients.add_argument("--python-executable", type=Path)

    prepare = subparsers.add_parser(
        "prepare-demo", help="create the synthetic Git continuation repository"
    )
    prepare.add_argument("--repository", type=Path, default=default_demo_repository())

    demo = subparsers.add_parser(
        "demo", help="ingest, verify, retrieve, and compile a cited handoff"
    )
    demo.add_argument("--database-url")
    demo.add_argument("--repository", type=Path, default=default_demo_repository())

    mcp = subparsers.add_parser("mcp", help="serve one exact local workspace over stdio")
    mcp.add_argument("--database-url")
    mcp.add_argument("--repository", type=Path)
    mcp.add_argument("--demo", action="store_true")

    api = subparsers.add_parser("api", help="serve the read-only synthetic demo API")
    api.add_argument("--database-url")
    api.add_argument("--host", default="127.0.0.1")
    api.add_argument("--port", type=int, default=8000)
    return parser


def _database_url(explicit: str | None) -> str:
    if explicit is not None:
        return explicit
    return os.getenv("THREADLINE_DATABASE_URL") or DEFAULT_DATABASE_URL


def main(arguments: Sequence[str] | None = None) -> None:
    parsed = _parser().parse_args(arguments)
    if parsed.command == "migrate":
        upgrade_database(_database_url(parsed.database_url))
        print("Threadline schema is current.")
        return
    if parsed.command == "init":
        path, manifest = initialize_manifest(
            parsed.repository,
            objective=parsed.objective,
            next_action=parsed.next_action,
        )
        print(
            json.dumps(
                {
                    "manifest": str(path),
                    "repository_id": str(manifest.repository_id),
                    "task_id": str(manifest.task.id),
                    "next": (
                        "Review threadline.json, then commit it before running "
                        "threadline sync."
                    ),
                },
                indent=2,
            )
        )
        return
    if parsed.command == "sync":
        synced = sync_local_workspace(
            parsed.repository,
            database_url=parsed.database_url,
            query=parsed.query,
        )
        print(
            json.dumps(
                {
                    "repository": str(synced.workspace.repository_path),
                    "task_id": str(synced.workspace.manifest.task.id),
                    "branch": synced.handoff.context_pack.repository_version.branch,
                    "commit": synced.handoff.context_pack.repository_version.commit_sha,
                    "context_version_id": str(synced.handoff.context_version.id),
                    "status": (
                        "partial"
                        if synced.handoff.content["unknowns"]
                        or synced.handoff.content["contradictions"]
                        else "ok"
                    ),
                },
                indent=2,
            )
        )
        return
    if parsed.command == "clients":
        print(
            json.dumps(
                build_client_profiles(
                    parsed.repository,
                    python_executable=parsed.python_executable,
                ),
                indent=2,
            )
        )
        return
    if parsed.command == "prepare-demo":
        path = prepare_demo_repository(parsed.repository)
        print(path)
        return
    if parsed.command == "mcp":
        if parsed.demo:
            serve_demo_mcp(_database_url(parsed.database_url))
            return
        serve_workspace_mcp(parsed.repository or Path.cwd(), parsed.database_url)
        return
    if parsed.command == "api":
        uvicorn.run(
            create_app(_database_url(parsed.database_url)),
            host=parsed.host,
            port=parsed.port,
        )
        return
    result = run_demo(_database_url(parsed.database_url), parsed.repository)
    print(
        json.dumps(
            {
                "repository": str(result.repository_path),
                "handoff_id": str(result.handoff.handoff.id),
                "context_version_id": str(result.handoff.context_version.id),
                **result.handoff.content,
            },
            indent=2,
            default=str,
        )
    )
