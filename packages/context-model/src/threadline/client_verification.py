"""Executable verification for generated MCP client profiles."""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import tomllib
from pathlib import Path
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from threadline.client_profiles import build_client_profiles


async def _probe_server(
    server: dict[str, Any],
    root: Path,
    *,
    expected_identity: dict[str, str],
) -> dict[str, Any]:
    parameters = StdioServerParameters(
        command=str(server["command"]),
        args=[str(item) for item in server["args"]],
        cwd=root,
    )
    async with (
        stdio_client(parameters) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        initialized = await session.initialize()
        tools = await session.list_tools()
        status = await session.call_tool("get_workspace_status", {})
        structured = status.structured_content
        if status.is_error or not isinstance(structured, dict):
            return {
                "verified": False,
                "server": initialized.server_info.name,
                "tools": sorted(item.name for item in tools.tools),
                "reason": "Threadline did not return a structured workspace identity.",
            }
        repository = structured.get("repository")
        data = structured.get("data")
        if not isinstance(repository, dict) or not isinstance(data, dict):
            return {
                "verified": False,
                "server": initialized.server_info.name,
                "tools": sorted(item.name for item in tools.tools),
                "reason": "Threadline returned an incomplete workspace identity.",
            }
        actual_identity = {
            "repository_id": str(repository.get("id", "")),
            "branch": str(repository.get("branch", "")),
            "commit": str(repository.get("commit", "")),
            "task_id": str(data.get("task_id", "")),
        }
        identity_matches = actual_identity == expected_identity
        return {
            "verified": (
                initialized.server_info.name == "Threadline"
                and bool(tools.tools)
                and identity_matches
            ),
            "server": initialized.server_info.name,
            "tools": sorted(item.name for item in tools.tools),
            "identity": actual_identity,
            "expected_identity": expected_identity,
            "identity_matches": identity_matches,
            "reason": (
                "Configured MCP server returned this repository's exact identity."
                if identity_matches
                else "Configured MCP server returned a different repository identity."
            ),
        }


def _configured_server(
    target: Path,
    client_name: str,
    profile: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    """Read the server the client will load instead of rebuilding a parallel one."""

    server_key = str(profile.get("server_key", "threadline"))
    try:
        if client_name == "codex":
            payload = tomllib.loads(target.read_text(encoding="utf-8"))
            container = payload.get("mcp_servers", {})
        else:
            payload = json.loads(target.read_text(encoding="utf-8"))
            container_key = "servers" if client_name == "vscode" else "mcpServers"
            container = payload.get(container_key, {}) if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError, tomllib.TOMLDecodeError) as error:
        return None, f"Client profile is unreadable: {error}"
    if not isinstance(container, dict):
        return None, "Client profile does not contain an MCP server map."
    server = container.get(server_key)
    if not isinstance(server, dict):
        return None, f"Client profile does not contain expected server {server_key!r}."
    command = server.get("command")
    args = server.get("args")
    if not isinstance(command, str) or not isinstance(args, list):
        return None, f"Configured server {server_key!r} is malformed."
    return server, None


def _codex_trust(root: Path) -> dict[str, Any]:
    config_path = Path.home() / ".codex" / "config.toml"
    trusted = False
    if config_path.is_file():
        try:
            payload = tomllib.loads(config_path.read_text(encoding="utf-8"))
            projects = payload.get("projects", {})
            project = projects.get(str(root)) if isinstance(projects, dict) else None
            trusted = isinstance(project, dict) and project.get("trust_level") == "trusted"
        except (OSError, tomllib.TOMLDecodeError):
            trusted = False
    return {
        "trusted": trusted,
        "reason": (
            "Codex has explicitly trusted this repository."
            if trusted
            else (
                "Codex intentionally ignores project .codex/config.toml files until the "
                "repository is trusted. Open this repository in Codex, review it, and choose Trust."
            )
        ),
        "documentation": ("https://learn.chatgpt.com/docs/config-file/config-reference#configtoml"),
    }


def _codex_registration(root: Path) -> dict[str, Any]:
    executable = shutil.which("codex")
    bundled = Path("/Applications/ChatGPT.app/Contents/Resources/codex")
    if executable is None and bundled.is_file():
        executable = str(bundled)
    if executable is None:
        return {"verified": False, "reason": "Codex CLI was not found on this machine."}
    result = subprocess.run(
        [executable, "mcp", "list", "--json"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    if result.returncode != 0:
        return {
            "verified": False,
            "reason": result.stderr.strip() or "Codex could not inspect MCP registration.",
        }
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"verified": False, "reason": "Codex returned an unreadable MCP list."}
    servers = payload if isinstance(payload, list) else payload.get("servers", [])
    names = {
        str(item.get("name"))
        for item in servers
        if isinstance(item, dict) and item.get("name") is not None
    }
    return {
        "verified": "threadline" in names,
        "reason": (
            "Codex reports the Threadline MCP server as registered."
            if "threadline" in names
            else "Codex does not report Threadline yet; trust and reopen this repository."
        ),
    }


def verify_client_connection(
    repository_path: Path,
    client_name: str,
    *,
    python_executable: Path | None = None,
) -> dict[str, Any]:
    """Verify the written profile and perform a real stdio MCP handshake."""

    profiles = build_client_profiles(
        repository_path,
        python_executable=python_executable,
    )
    clients = profiles["clients"]
    if client_name not in clients:
        supported = ", ".join(sorted(clients))
        raise ValueError(f"unsupported client {client_name!r}; choose one of: {supported}")
    root = Path(str(profiles["repository"]))
    target = root / str(clients[client_name]["path"])
    profile_present = target.is_file()
    if not profile_present:
        return {
            "verified": False,
            "client": client_name,
            "profile": {"present": False, "path": str(target)},
            "server": {"verified": False, "reason": "Connect this client first."},
            "next_action": f"threadline connect {client_name} {root}",
        }
    configured_server, profile_error = _configured_server(
        target,
        client_name,
        clients[client_name],
    )
    expected_identity = {
        "repository_id": str(profiles["repository_id"]),
        "branch": str(profiles["repository_version"]["branch"]),
        "commit": str(profiles["repository_version"]["commit"]),
        "task_id": str(profiles["task_id"]),
    }
    if configured_server is None:
        server = {"verified": False, "reason": profile_error}
    else:
        try:
            server = asyncio.run(
                _probe_server(
                    configured_server,
                    root,
                    expected_identity=expected_identity,
                )
            )
        except Exception as error:
            server = {"verified": False, "reason": f"MCP handshake failed: {error}"}
    native: dict[str, Any] = {
        "verified": bool(server.get("verified")),
        "reason": (
            "Project profile is present and its configured server returned the expected identity."
            if server.get("verified")
            else str(server.get("reason", "The configured server identity could not be verified."))
        ),
    }
    trust: dict[str, Any] | None = None
    if client_name == "codex":
        trust = _codex_trust(root)
        native = (
            _codex_registration(root)
            if trust["trusted"]
            else {
                "verified": False,
                "reason": trust["reason"],
            }
        )
    verified = bool(server.get("verified")) and bool(native.get("verified"))
    active_session: dict[str, Any] | None = None
    if client_name == "antigravity":
        active_session = {
            "verified": None,
            "reason": (
                "The CLI cannot inspect an already-open Antigravity process. Restart Antigravity "
                "after connecting, then ask it to report Threadline's exact repository and commit."
            ),
        }
    return {
        "verified": verified,
        "client": client_name,
        "profile": {
            "present": True,
            "path": str(target),
            "server_key": str(clients[client_name].get("server_key", "threadline")),
        },
        "server": server,
        "native_client": native,
        "active_session": active_session,
        "trust": trust,
        "next_action": (
            (
                "Restart Antigravity, then ask it: Use Threadline to report the exact repository, "
                "commit, task, and next action."
                if client_name == "antigravity"
                else (
                    "Ask the client: Use Threadline to report the current task, commit, "
                    "and next action."
                )
            )
            if verified
            else (
                f"threadline connect {client_name} {root}"
                if configured_server is None
                else str(native.get("reason", "Reload the client and run this check again."))
            )
        ),
    }
