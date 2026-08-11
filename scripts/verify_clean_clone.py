"""Verify GitHub-clone onboarding without relying on this checkout's environment."""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def _environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.pop("THREADLINE_DATABASE_URL", None)
    environment.pop("PYTHONPATH", None)
    return environment


def _run(
    command: list[str],
    *,
    cwd: Path,
    timeout: int = 300,
) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=_environment(),
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Clean-clone command failed ({' '.join(command)}):\n"
            f"{result.stdout}{result.stderr}"
        )
    return result.stdout.strip()


def _git(repository: Path, *arguments: str) -> str:
    return _run(["git", "-C", str(repository), *arguments], cwd=repository)


def _export_head(destination: Path) -> None:
    archive = subprocess.run(
        ["git", "-C", str(ROOT), "archive", "--format=tar", "HEAD"],
        check=True,
        capture_output=True,
        timeout=30,
    ).stdout
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as bundle:
        bundle.extractall(destination, filter="data")


def _create_repository(destination: Path) -> None:
    destination.mkdir()
    _git(destination, "init", "-b", "main")
    (destination / "parser.py").write_text(
        "def parse(value: str) -> str:\n    return value.strip()\n",
        encoding="utf-8",
    )
    _git(destination, "add", "parser.py")
    _git(
        destination,
        "-c",
        "user.name=Threadline Clean Clone",
        "-c",
        "user.email=clean-clone@example.invalid",
        "commit",
        "-m",
        "Create parser project",
    )


async def _verify_mcp(repository: Path) -> dict[str, Any]:
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "threadline", "mcp", "--repository", str(repository)],
        cwd=ROOT,
        env=_environment(),
    )
    async with (
        stdio_client(parameters) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        initialized = await session.initialize()
        tools = await session.list_tools()
        workspace_result = await session.call_tool("get_workspace_status", {})
        if workspace_result.is_error or workspace_result.structured_content is None:
            raise RuntimeError("Clean-clone MCP workspace bootstrap failed")
        workspace = workspace_result.structured_content
        context_result = await session.call_tool(
            "get_task_context",
            {
                "task_id": workspace["data"]["task_id"],
                "branch": workspace["repository"]["branch"],
                "commit_sha": workspace["repository"]["commit"],
            },
        )
        if context_result.is_error or context_result.structured_content is None:
            raise RuntimeError("Clean-clone MCP task-context call failed")
        context = context_result.structured_content
        return {
            "server": initialized.server_info.name,
            "tool_count": len(tools.tools),
            "workspace_status": workspace["status"],
            "handoff_current": workspace["data"]["handoff_current"],
            "context_status": context["status"],
            "citation_count": len(context["citations"]),
        }


def _run_inner(repository: Path) -> None:
    result = asyncio.run(_verify_mcp(repository.resolve()))
    print(json.dumps(result))


def _verify_clean_clone() -> None:
    with tempfile.TemporaryDirectory(prefix="threadline-clean-clone-") as temporary:
        root = Path(temporary)
        checkout = root / "threadline"
        checkout.mkdir()
        _export_head(checkout)

        virtual_environment = checkout / ".venv"
        _run([sys.executable, "-m", "venv", str(virtual_environment)], cwd=checkout)
        python = virtual_environment / "bin" / "python"
        threadline = virtual_environment / "bin" / "threadline"
        _run(
            [str(python), "-m", "pip", "install", "--disable-pip-version-check", "-e", "."],
            cwd=checkout,
        )

        repository = root / "user-repository"
        _create_repository(repository)
        initialized = json.loads(
            _run(
                [
                    str(threadline),
                    "init",
                    str(repository),
                    "--objective",
                    "Preserve parser behavior across an agent handoff",
                    "--next-action",
                    "Add a whitespace-only integration test",
                ],
                cwd=checkout,
            )
        )
        _git(repository, "add", "threadline.json")
        _git(
            repository,
            "-c",
            "user.name=Threadline Clean Clone",
            "-c",
            "user.email=clean-clone@example.invalid",
            "commit",
            "-m",
            "Add Threadline context",
        )
        synchronized = json.loads(
            _run([str(threadline), "sync", str(repository)], cwd=checkout)
        )
        profiles = json.loads(
            _run(
                [
                    str(threadline),
                    "clients",
                    str(repository),
                    "--python-executable",
                    str(python),
                ],
                cwd=checkout,
            )
        )
        mcp = json.loads(
            _run(
                [
                    str(python),
                    str(checkout / "scripts" / "verify_clean_clone.py"),
                    "--verify-mcp",
                    str(repository),
                ],
                cwd=checkout,
            )
        )

        if set(profiles["clients"]) != {
            "antigravity",
            "claude",
            "codex",
            "cursor",
            "vscode",
        }:
            raise RuntimeError("Clean-clone client profile set is incomplete")
        if _git(repository, "status", "--porcelain=v1", "--untracked-files=all"):
            raise RuntimeError("Threadline dirtied the clean-clone user repository")
        if not (repository / ".git" / "threadline" / "threadline.db").is_file():
            raise RuntimeError("Repository-private SQLite state was not created")
        if not mcp["handoff_current"] or mcp["tool_count"] != 6:
            raise RuntimeError("Clean-clone MCP proof returned incomplete state")

        print(
            json.dumps(
                {
                    "status": "passed",
                    "installed_version": "0.1.0",
                    "task_id": initialized["task_id"],
                    "synchronized_commit": synchronized["commit"],
                    "clients": sorted(profiles["clients"]),
                    "mcp": mcp,
                    "working_tree_clean": True,
                    "api_keys_required": False,
                    "external_database_required": False,
                },
                indent=2,
            )
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-mcp", type=Path)
    arguments = parser.parse_args()
    if arguments.verify_mcp is not None:
        _run_inner(arguments.verify_mcp)
        return
    _verify_clean_clone()


if __name__ == "__main__":
    main()
