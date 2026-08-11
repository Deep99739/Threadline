"""Generate reviewable, project-scoped MCP configuration without mutating client settings."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from threadline.workspace import LocalWorkspace, load_local_workspace

OFFICIAL_DOCUMENTATION = {
    "codex": "https://developers.openai.com/codex/mcp",
    "claude": "https://docs.anthropic.com/en/docs/claude-code/mcp",
    "cursor": "https://docs.cursor.com/context/model-context-protocol",
    "vscode": "https://code.visualstudio.com/docs/agent-customization/mcp-servers",
    "antigravity": "https://antigravity.google/docs/mcp",
}


def _server(workspace: LocalWorkspace, python_executable: Path) -> dict[str, Any]:
    executable = python_executable.expanduser().absolute()
    if not executable.is_file():
        raise FileNotFoundError(f"Python executable was not found: {executable}")
    return {
        # Do not resolve the venv symlink: its original path selects the installed environment.
        "command": str(executable),
        "args": [
            "-m",
            "threadline",
            "mcp",
            "--repository",
            str(workspace.repository_path),
        ],
    }


def _codex_toml(server: dict[str, Any], repository_path: Path) -> str:
    command = json.dumps(server["command"])
    arguments = ", ".join(json.dumps(item) for item in server["args"])
    cwd = json.dumps(str(repository_path))
    return (
        "[mcp_servers.threadline]\n"
        f"command = {command}\n"
        f"args = [{arguments}]\n"
        f"cwd = {cwd}\n"
        "enabled = true\n"
    )


def build_client_profiles(
    repository_path: Path,
    *,
    python_executable: Path | None = None,
) -> dict[str, Any]:
    """Return configurations for supported clients; never write them automatically."""

    workspace = load_local_workspace(repository_path)
    executable = python_executable or Path(sys.executable)
    server = _server(workspace, executable)
    standard = {"mcpServers": {"threadline": server}}
    vscode = {
        "servers": {
            "threadline": {
                "type": "stdio",
                **server,
            }
        }
    }
    return {
        "schema_version": 1,
        "repository": str(workspace.repository_path),
        "task_id": str(workspace.manifest.task.id),
        "server": {
            **server,
            "transport": "stdio",
            "tools": "read-only",
            "local_database": str(
                workspace.repository_path / ".threadline" / "threadline.db"
            ),
        },
        "clients": {
            "codex": {
                "path": ".codex/config.toml",
                "merge": True,
                "content": _codex_toml(server, workspace.repository_path),
                "user_install_command": [
                    "codex",
                    "mcp",
                    "add",
                    "threadline",
                    "--",
                    server["command"],
                    *server["args"],
                ],
                "documentation": OFFICIAL_DOCUMENTATION["codex"],
            },
            "claude": {
                "path": ".mcp.json",
                "merge": True,
                "content": standard,
                "project_install_command": [
                    "claude",
                    "mcp",
                    "add",
                    "threadline",
                    "--scope",
                    "project",
                    "--",
                    server["command"],
                    *server["args"],
                ],
                "documentation": OFFICIAL_DOCUMENTATION["claude"],
            },
            "cursor": {
                "path": ".cursor/mcp.json",
                "merge": True,
                "content": standard,
                "documentation": OFFICIAL_DOCUMENTATION["cursor"],
            },
            "vscode": {
                "path": ".vscode/mcp.json",
                "merge": True,
                "content": vscode,
                "documentation": OFFICIAL_DOCUMENTATION["vscode"],
            },
            "antigravity": {
                "path": ".agents/mcp_config.json",
                "merge": True,
                "content": standard,
                "documentation": OFFICIAL_DOCUMENTATION["antigravity"],
            },
        },
        "safety": {
            "writes_client_configuration": False,
            "contains_secrets": False,
            "review_before_installing": True,
            "note": (
                "Local MCP servers execute code. Review the command and merge only the "
                "profile for the client you trust."
            ),
        },
    }
