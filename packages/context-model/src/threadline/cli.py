"""Command-line entry point for Threadline's local vertical slice."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
from pathlib import Path

from threadline.demo import default_demo_repository, prepare_demo_repository, run_demo
from threadline.mcp_runtime import serve_demo_mcp
from threadline.migrations import upgrade_database

DEFAULT_DATABASE_URL = "postgresql+psycopg://threadline:threadline_local@localhost:55432/threadline"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="threadline")
    subparsers = parser.add_subparsers(dest="command", required=True)

    migrate = subparsers.add_parser("migrate", help="apply explicit schema migrations")
    migrate.add_argument("--database-url")

    prepare = subparsers.add_parser(
        "prepare-demo", help="create the synthetic Git continuation repository"
    )
    prepare.add_argument("--repository", type=Path, default=default_demo_repository())

    demo = subparsers.add_parser(
        "demo", help="ingest, verify, retrieve, and compile a cited handoff"
    )
    demo.add_argument("--database-url")
    demo.add_argument("--repository", type=Path, default=default_demo_repository())

    mcp = subparsers.add_parser("mcp", help="serve the seeded local workspace over stdio")
    mcp.add_argument("--database-url")
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
    if parsed.command == "prepare-demo":
        path = prepare_demo_repository(parsed.repository)
        print(path)
        return
    if parsed.command == "mcp":
        serve_demo_mcp(_database_url(parsed.database_url))
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
