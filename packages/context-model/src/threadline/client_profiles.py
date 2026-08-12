"""Generate reviewable, project-scoped MCP configuration without mutating client settings."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from threadline.git_repository import threadline_git_state_path
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
            "local_database": str(threadline_git_state_path(workspace.repository_path)),
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


def _merge_json(current: dict[str, Any], addition: dict[str, Any]) -> dict[str, Any]:
    merged = dict(current)
    for key, value in addition.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = _merge_json(existing, value)
        else:
            merged[key] = value
    return merged


def connect_client(
    repository_path: Path,
    client_name: str,
    *,
    python_executable: Path | None = None,
) -> dict[str, Any]:
    """Write one explicitly requested project profile without touching global settings."""

    profiles = build_client_profiles(
        repository_path,
        python_executable=python_executable,
    )
    clients = profiles["clients"]
    if client_name not in clients:
        supported = ", ".join(sorted(clients))
        raise ValueError(f"unsupported client {client_name!r}; choose one of: {supported}")

    root = Path(str(profiles["repository"]))
    profile = clients[client_name]
    target = root / str(profile["path"])
    target.parent.mkdir(parents=True, exist_ok=True)
    if client_name == "codex":
        addition = str(profile["content"])
        if target.exists():
            current = target.read_text(encoding="utf-8")
            if "[mcp_servers.threadline]" in current:
                raise FileExistsError(
                    "Codex already has a project Threadline entry; review it before replacing"
                )
            if current and not current.endswith("\n"):
                current += "\n"
            rendered = current + ("\n" if current else "") + addition
        else:
            rendered = addition
    else:
        addition_payload = profile["content"]
        if not isinstance(addition_payload, dict):
            raise TypeError("client JSON profile is not an object")
        if target.exists():
            existing_payload = json.loads(target.read_text(encoding="utf-8"))
            if not isinstance(existing_payload, dict):
                raise ValueError(f"existing client configuration is not an object: {target}")
        else:
            existing_payload = {}
        rendered = json.dumps(_merge_json(existing_payload, addition_payload), indent=2) + "\n"

    previous = target.read_text(encoding="utf-8") if target.exists() else None
    changed = previous != rendered
    if changed:
        target.write_text(rendered, encoding="utf-8")
    return {
        "client": client_name,
        "path": str(target),
        "changed": changed,
        "scope": "project",
        "contains_secrets": False,
        "tools": "read-only",
        "next_steps": [
            f"Review and commit {target.relative_to(root)} if the team should share it.",
            "Run threadline doctor . to confirm the exact handoff is current.",
            "Open the client and approve the local MCP server when prompted.",
        ],
    }
