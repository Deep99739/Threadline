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


async def _probe_server(server: dict[str, Any], root: Path) -> dict[str, Any]:
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
        return {
            "verified": initialized.server_info.name == "Threadline" and bool(tools.tools),
            "server": initialized.server_info.name,
            "tools": sorted(item.name for item in tools.tools),
        }


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
        "documentation": (
            "https://learn.chatgpt.com/docs/config-file/config-reference#configtoml"
        ),
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
    try:
        server = asyncio.run(_probe_server(profiles["server"], root))
    except Exception as error:
        server = {"verified": False, "reason": f"MCP handshake failed: {error}"}
    native: dict[str, Any] = {"verified": True, "reason": "Project profile is present."}
    trust: dict[str, Any] | None = None
    if client_name == "codex":
        trust = _codex_trust(root)
        native = _codex_registration(root) if trust["trusted"] else {
            "verified": False,
            "reason": trust["reason"],
        }
    verified = bool(server.get("verified")) and bool(native.get("verified"))
    return {
        "verified": verified,
        "client": client_name,
        "profile": {"present": True, "path": str(target)},
        "server": server,
        "native_client": native,
        "trust": trust,
        "next_action": (
            "Ask the client: Use Threadline to report the current task, commit, and next action."
            if verified
            else str(native.get("reason", "Reload the client and run this check again."))
        ),
    }
