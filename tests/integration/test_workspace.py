from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from tests.helpers import PROJECT_ROOT, git

from threadline.cli import main
from threadline.client_profiles import OFFICIAL_DOCUMENTATION, build_client_profiles
from threadline.manifest import initialize_manifest
from threadline.workspace import (
    load_local_workspace,
    sync_local_workspace,
    workspace_database_url,
)


def _initialized_repository(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "real-project"
    root.mkdir()
    git(root, "init", "-b", "main")
    (root / "parser.py").write_text("def parse(value: str) -> str:\n    return value.strip()\n")
    git(root, "add", "parser.py")
    git(
        root,
        "-c",
        "user.name=Repository Owner",
        "-c",
        "user.email=owner@example.invalid",
        "commit",
        "-m",
        "Add parser",
    )
    _, manifest = initialize_manifest(
        root,
        objective="Make parser continuation evidence available to the next agent",
        next_action="Add an integration test for whitespace-only input",
    )
    return root, str(manifest.task.id)


def _commit_manifest(root: Path) -> None:
    git(root, "add", "threadline.json")
    git(
        root,
        "-c",
        "user.name=Repository Owner",
        "-c",
        "user.email=owner@example.invalid",
        "commit",
        "-m",
        "Add Threadline context",
    )


def test_workspace_requires_committed_configuration_and_syncs_exact_head(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("THREADLINE_DATABASE_URL", raising=False)
    root, task_id = _initialized_repository(tmp_path)

    with pytest.raises(ValueError, match="not committed"):
        load_local_workspace(root)

    _commit_manifest(root)
    first = load_local_workspace(root)
    second = load_local_workspace(root)
    assert first.scope == second.scope
    assert str(first.manifest.task.id) == task_id
    assert workspace_database_url(first).endswith("/.git/threadline/threadline.db")

    synced = sync_local_workspace(root)

    assert (root / ".git" / "threadline" / "threadline.db").is_file()
    assert git(root, "status", "--porcelain=v1", "--untracked-files=all") == ""
    assert synced.handoff.context_pack.repository_version.commit_sha == git(
        root, "rev-parse", "HEAD"
    )
    assert synced.handoff.content["next_action"] == (
        "Add an integration test for whitespace-only input"
    )
    task_items = [
        item for item in synced.handoff.context_pack.items if item.entity_type == "task"
    ]
    assert len(task_items) == 1
    assert task_items[0].citations[0].locator.uri.endswith("/threadline.json")

    manifest_path = root / "threadline.json"
    manifest_path.write_text(manifest_path.read_text().replace("IN_PROGRESS", "PAUSED"))
    with pytest.raises(ValueError, match="uncommitted changes"):
        load_local_workspace(root)


def test_cli_init_and_sync_return_machine_readable_state(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "cli-project"
    root.mkdir()
    git(root, "init", "-b", "main")
    (root / "README.md").write_text("# CLI project\n")
    git(root, "add", "README.md")
    git(
        root,
        "-c",
        "user.name=Repository Owner",
        "-c",
        "user.email=owner@example.invalid",
        "commit",
        "-m",
        "Initialize CLI project",
    )

    main(
        [
            "init",
            str(root),
            "--objective",
            "Continue the CLI project",
            "--next-action",
            "Implement the next command",
        ]
    )
    initialized = json.loads(capsys.readouterr().out)
    assert initialized["manifest"] == str(root / "threadline.json")
    _commit_manifest(root)

    database_url = f"sqlite+pysqlite:///{tmp_path / 'cli-workspace.db'}"
    main(["sync", str(root), "--database-url", database_url])
    synced = json.loads(capsys.readouterr().out)
    assert synced["repository"] == str(root)
    assert synced["commit"] == git(root, "rev-parse", "HEAD")
    assert synced["status"] == "ok"

    main(
        [
            "clients",
            str(root),
            "--python-executable",
            str(PROJECT_ROOT / ".venv" / "bin" / "python"),
        ]
    )
    profiles = json.loads(capsys.readouterr().out)
    assert set(profiles["clients"]) == {
        "antigravity",
        "claude",
        "codex",
        "cursor",
        "vscode",
    }
    assert profiles["safety"]["writes_client_configuration"] is False


def test_client_profiles_are_project_scoped_reviewable_and_secret_free(tmp_path: Path) -> None:
    root, _ = _initialized_repository(tmp_path)
    _commit_manifest(root)

    profiles = build_client_profiles(
        root,
        python_executable=PROJECT_ROOT / ".venv" / "bin" / "python",
    )

    clients = profiles["clients"]
    assert profiles["server"]["command"] == str(PROJECT_ROOT / ".venv" / "bin" / "python")
    assert clients["cursor"]["path"] == ".cursor/mcp.json"
    assert clients["vscode"]["content"]["servers"]["threadline"]["type"] == "stdio"
    assert clients["antigravity"]["path"] == ".agents/mcp_config.json"
    assert clients["claude"]["path"] == ".mcp.json"
    codex = tomllib.loads(clients["codex"]["content"])["mcp_servers"]["threadline"]
    assert codex["args"][-2:] == ["--repository", str(root)]
    assert codex["cwd"] == str(root)
    assert {
        name: client["documentation"] for name, client in clients.items()
    } == OFFICIAL_DOCUMENTATION
    serialized = json.dumps(profiles)
    assert "API_KEY" not in serialized
    assert "DATABASE_URL" not in serialized
    assert not (root / ".codex").exists()
    assert not (root / ".cursor").exists()
    assert not (root / ".vscode").exists()
    assert not (root / ".agents").exists()
    assert not (root / ".mcp.json").exists()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_real_stdio_workspace_server_exposes_committed_task(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("THREADLINE_DATABASE_URL", raising=False)
    root, task_id = _initialized_repository(tmp_path)
    _commit_manifest(root)
    profiles = build_client_profiles(
        root,
        python_executable=PROJECT_ROOT / ".venv" / "bin" / "python",
    )
    server = profiles["server"]
    parameters = StdioServerParameters(
        command=server["command"],
        args=server["args"],
        cwd=PROJECT_ROOT,
    )

    async with (
        stdio_client(parameters) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        initialized = await session.initialize()
        assert initialized.server_info.name == "Threadline"
        bootstrap = await session.call_tool("get_workspace_status", {})
        assert bootstrap.is_error is False
        bootstrap_content = bootstrap.structured_content
        assert bootstrap_content["data"]["task_id"] == task_id
        assert bootstrap_content["data"]["handoff_current"] is True
        result = await session.call_tool(
            "get_task_context",
            {
                "task_id": task_id,
                "branch": bootstrap_content["repository"]["branch"],
                "commit_sha": bootstrap_content["repository"]["commit"],
            },
        )

    assert result.is_error is False
    assert result.structured_content["status"] == "ok"
    assert result.structured_content["data"]["objective"].startswith("Make parser")
    assert result.structured_content["citations"][0]["locator"]["uri"].endswith(
        "/threadline.json"
    )
    assert git(root, "status", "--porcelain=v1", "--untracked-files=all") == ""
