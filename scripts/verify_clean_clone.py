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
    _git(destination, "config", "user.name", "Threadline Clean Clone")
    _git(destination, "config", "user.email", "clean-clone@example.invalid")
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
        graph_result = await session.call_tool(
            "trace_code_symbol",
            {
                "task_id": workspace["data"]["task_id"],
                "branch": workspace["repository"]["branch"],
                "commit_sha": workspace["repository"]["commit"],
                "symbol": "parser.parse",
                "max_depth": 1,
                "max_nodes": 10,
            },
        )
        if graph_result.is_error or graph_result.structured_content is None:
            raise RuntimeError("Clean-clone MCP code graph call failed")
        graph = graph_result.structured_content
        return {
            "server": initialized.server_info.name,
            "tool_count": len(tools.tools),
            "workspace_status": workspace["status"],
            "handoff_current": workspace["data"]["handoff_current"],
            "context_status": context["status"],
            "citation_count": len(context["citations"]),
            "graph_node_count": len(graph["data"]["nodes"]),
            "graph_citation_count": len(graph["citations"]),
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
            [str(python), "-m", "pip", "install", "--disable-pip-version-check", "."],
            cwd=checkout,
        )
        installed_module = Path(
            _run(
                [str(python), "-c", "import threadline; print(threadline.__file__)"],
                cwd=root,
            )
        ).resolve()
        source_package = (
            checkout / "packages" / "context-model" / "src" / "threadline"
        ).resolve()
        if (
            source_package == installed_module.parent
            or "site-packages" not in installed_module.parts
        ):
            raise RuntimeError("Clean-clone proof used the source checkout instead of the wheel")

        repository = root / "user-repository"
        _create_repository(repository)
        onboarded = json.loads(
            _run(
                [
                    str(threadline),
                    "onboard",
                    str(repository),
                    "--objective",
                    "Preserve parser behavior across an agent handoff",
                    "--next-action",
                    "Add a whitespace-only integration test",
                    "--client",
                    "cursor",
                    "--python-executable",
                    str(python),
                ],
                cwd=checkout,
            )
        )
        synchronized = {"commit": onboarded["context_commit"]}
        diagnosed = json.loads(
            _run([str(threadline), "doctor", str(repository)], cwd=checkout)
        )
        rendered_handoff = _run(
            [str(threadline), "handoff", str(repository)],
            cwd=checkout,
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
        connected = onboarded["client"]
        cursor_profile = json.loads(
            (repository / ".cursor" / "mcp.json").read_text(encoding="utf-8")
        )
        checked = json.loads(
            _run(
                [
                    str(threadline),
                    "check",
                    str(repository),
                    "--scope",
                    "FULL",
                    "--include",
                    "parser.py",
                    "--",
                    str(python),
                    "-c",
                    "raise SystemExit(0)",
                ],
                cwd=checkout,
            )
        )
        _git(repository, "add", "parser.py", "threadline.json", "threadline/test-report.json")
        _git(
            repository,
            "-c",
            "user.name=Threadline Clean Clone",
            "-c",
            "user.email=clean-clone@example.invalid",
            "commit",
            "-m",
            "Record parser verification",
        )
        synchronized = json.loads(
            _run([str(threadline), "sync", str(repository)], cwd=checkout)
        )
        verified_handoff = json.loads(
            _run(
                [str(threadline), "handoff", str(repository), "--format", "json"],
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
        if not diagnosed["ready"] or not diagnosed["handoff"]["current"]:
            raise RuntimeError("Clean-clone doctor did not confirm the current handoff")
        if "# Threadline handoff" not in rendered_handoff or "repo://" not in rendered_handoff:
            raise RuntimeError("Clean-clone terminal handoff omitted evidence")
        if not connected["changed"] or "threadline" not in cursor_profile["mcpServers"]:
            raise RuntimeError("Clean-clone client connection was not written safely")
        if checked["status"] != "PASSED" or checked["raw_output_persisted"]:
            raise RuntimeError("Clean-clone command evidence did not preserve its trust contract")
        if not verified_handoff["verified_completed_work"]:
            raise RuntimeError("Clean-clone handoff omitted committed command verification")
        if _git(repository, "status", "--porcelain=v1", "--untracked-files=all"):
            raise RuntimeError("Threadline dirtied the clean-clone user repository")
        if not (repository / ".git" / "threadline" / "threadline.db").is_file():
            raise RuntimeError("Repository-private SQLite state was not created")
        if not mcp["handoff_current"] or mcp["tool_count"] != 8:
            raise RuntimeError("Clean-clone MCP proof returned incomplete state")
        if not mcp["graph_node_count"] or not mcp["graph_citation_count"]:
            raise RuntimeError("Clean-clone graph proof returned no cited symbols")

        print(
            json.dumps(
                {
                    "status": "passed",
                    "installed_version": "0.1.0",
                    "task_id": onboarded["task_id"],
                    "synchronized_commit": synchronized["commit"],
                    "installed_module": str(installed_module),
                    "clients": sorted(profiles["clients"]),
                    "doctor_ready": diagnosed["ready"],
                    "terminal_handoff_cited": "repo://" in rendered_handoff,
                    "connected_client": connected["client"],
                    "command_evidence_status": checked["status"],
                    "verified_work_count": len(
                        verified_handoff["verified_completed_work"]
                    ),
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
