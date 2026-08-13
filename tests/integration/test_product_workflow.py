from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from tests.helpers import git

from threadline.client_profiles import connect_client
from threadline.manifest import ProjectManifest, initialize_manifest
from threadline.product_workflow import (
    checkpoint_workspace,
    handoff_content,
    inspect_workspace,
    onboard_workspace,
    render_handoff_markdown,
)
from threadline.workspace import sync_local_workspace


def _repository(tmp_path: Path) -> Path:
    root = tmp_path / "adopted-project"
    root.mkdir()
    git(root, "init", "-b", "main")
    (root / "parser.py").write_text(
        "def parse(value: str) -> str:\n    return value.strip()\n",
        encoding="utf-8",
    )
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
    initialize_manifest(
        root,
        objective="Make parser continuation evidence available",
        next_action="Add an integration test for whitespace-only input",
    )
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
    return root


def _commit(root: Path, *paths: str, message: str) -> None:
    git(root, "add", *paths)
    git(
        root,
        "-c",
        "user.name=Repository Owner",
        "-c",
        "user.email=owner@example.invalid",
        "commit",
        "-m",
        message,
    )


def test_doctor_explains_missing_sync_then_confirms_current_handoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("THREADLINE_DATABASE_URL", raising=False)
    root = _repository(tmp_path)

    before = inspect_workspace(root)

    assert before["ready"] is False
    assert any(item["code"] == "sync_required" for item in before["checks"])
    assert before["requires_api_key"] is False
    assert not (root / ".git" / "threadline" / "threadline.db").exists()

    synced = sync_local_workspace(root)
    after = inspect_workspace(root)

    assert after["ready"] is True
    assert (
        after["repository"]["commit"] == synced.handoff.context_pack.repository_version.commit_sha
    )
    assert after["handoff"]["current"] is True
    assert after["next_command"] == f"threadline handoff {root}"


def test_connect_merges_one_project_client_without_overwriting_other_servers(
    tmp_path: Path,
) -> None:
    root = _repository(tmp_path)
    target = root / ".cursor" / "mcp.json"
    target.parent.mkdir()
    target.write_text(
        json.dumps({"mcpServers": {"existing": {"command": "existing-server"}}}),
        encoding="utf-8",
    )

    result = connect_client(
        root,
        "cursor",
        python_executable=Path(sys.executable),
    )
    payload = json.loads(target.read_text(encoding="utf-8"))

    assert result["changed"] is True
    assert result["path"] == str(target)
    assert payload["mcpServers"]["existing"]["command"] == "existing-server"
    assert payload["mcpServers"]["threadline"]["args"][-2:] == [
        "--repository",
        str(root),
    ]
    assert result["next_steps"][0].startswith("Review")
    assert git(root, "status", "--porcelain=v1", "--untracked-files=all") == ""


def test_onboard_creates_one_context_commit_and_returns_a_ready_clean_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("THREADLINE_DATABASE_URL", raising=False)
    root = tmp_path / "first-use-project"
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "Repository Owner")
    git(root, "config", "user.email", "owner@example.invalid")
    (root / "parser.py").write_text(
        "def parse(value: str) -> str:\n    return value.strip()\n",
        encoding="utf-8",
    )
    git(root, "add", "parser.py")
    git(root, "commit", "-m", "Add parser")
    coverage_probe = root / ".git" / "coverage-probe"
    coverage_probe.write_text(
        "#!/bin/sh\n"
        'if [ -n "${COVERAGE_PROCESS_START:-}" ] || '
        '[ -n "${COV_CORE_SOURCE:-}" ]; then exit 9; fi\n'
        f'exec {sys.executable} "$@"\n',
        encoding="utf-8",
    )
    coverage_probe.chmod(0o755)

    result = onboard_workspace(
        root,
        objective="Make parser continuation safe",
        next_action="Add whitespace integration coverage",
        client="codex",
        python_executable=coverage_probe,
    )

    assert result["ready"] is True
    assert result["commit_created"] == git(root, "rev-parse", "HEAD")
    assert result["context_commit"] == result["commit_created"]
    assert result["requires_api_key"] is False
    assert result["client"]["changed"] is True
    assert result["client"]["excluded_locally"] is True
    assert result["refresh_hooks"]["automatic_refresh"] is True
    assert set(result["refresh_hooks"]["installed"]) == {
        "post-checkout",
        "post-commit",
        "post-merge",
        "post-rewrite",
    }
    assert (root / ".codex" / "config.toml").is_file()
    assert (root / ".git" / "threadline" / "threadline.db").is_file()
    post_commit = root / ".git" / "hooks" / "post-commit"
    assert "unset COVERAGE_PROCESS_START COVERAGE_FILE COV_CORE_SOURCE" in post_commit.read_text(
        encoding="utf-8"
    )
    assert git(root, "log", "-1", "--pretty=%s") == "Add Threadline context"
    assert git(root, "ls-files", "threadline.json") == "threadline.json"
    assert git(root, "status", "--porcelain=v1", "--untracked-files=all") == ""
    assert inspect_workspace(root)["ready"] is True

    (root / "parser.py").write_text(
        "def parse(value: str) -> str:\n    return value.strip().lower()\n",
        encoding="utf-8",
    )
    git(root, "add", "parser.py")
    command_environment = os.environ.copy()
    command_environment.update(
        {
            "COVERAGE_PROCESS_START": "/tmp/coverage-config",
            "COV_CORE_SOURCE": "threadline",
        }
    )
    subprocess.run(
        ["git", "-C", str(root), "commit", "-m", "Normalize parser output"],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
        env=command_environment,
    )

    refreshed = inspect_workspace(root)
    assert refreshed["ready"] is True
    assert refreshed["repository"]["commit"] == git(root, "rev-parse", "HEAD")

    repeated = onboard_workspace(
        root,
        objective="Make parser continuation safe",
        next_action="Add whitespace integration coverage",
        client="codex",
        python_executable=coverage_probe,
    )

    assert repeated["ready"] is True
    assert repeated["commit_created"] is None
    assert repeated["client"]["changed"] is False
    assert repeated["refresh_hooks"]["installed"] == []
    assert set(repeated["refresh_hooks"]["existing"]) == {
        "post-checkout",
        "post-commit",
        "post-merge",
        "post-rewrite",
    }
    assert git(root, "status", "--porcelain=v1", "--untracked-files=all") == ""


def test_onboard_preserves_an_existing_git_hook_and_reports_manual_refresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("THREADLINE_DATABASE_URL", raising=False)
    root = tmp_path / "hooked-project"
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "Repository Owner")
    git(root, "config", "user.email", "owner@example.invalid")
    (root / "README.md").write_text("# Hooked project\n", encoding="utf-8")
    git(root, "add", "README.md")
    git(root, "commit", "-m", "Initialize project")
    existing_hook = root / ".git" / "hooks" / "post-commit"
    existing_hook.write_text("#!/bin/sh\nprintf 'custom hook\\n'\n", encoding="utf-8")
    existing_hook.chmod(0o755)

    result = onboard_workspace(
        root,
        objective="Preserve project continuation",
        next_action="Inspect the repository",
        client="codex",
        python_executable=Path(sys.executable),
    )

    assert result["ready"] is True
    assert result["refresh_hooks"]["automatic_refresh"] is False
    assert result["refresh_hooks"]["blocked"] == ["post-commit"]
    assert existing_hook.read_text(encoding="utf-8") == ("#!/bin/sh\nprintf 'custom hook\\n'\n")


def test_onboard_refuses_existing_work_without_creating_product_files(tmp_path: Path) -> None:
    root = tmp_path / "dirty-project"
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "Repository Owner")
    git(root, "config", "user.email", "owner@example.invalid")
    (root / "README.md").write_text("# Project\n", encoding="utf-8")
    git(root, "add", "README.md")
    git(root, "commit", "-m", "Initialize project")
    (root / "unfinished.py").write_text("raise NotImplementedError\n", encoding="utf-8")

    with pytest.raises(ValueError, match="onboarding requires a clean working tree"):
        onboard_workspace(
            root,
            objective="Continue unfinished work",
            next_action="Implement the function",
            client="codex",
            python_executable=Path(sys.executable),
        )

    assert not (root / "threadline.json").exists()
    assert not (root / ".codex").exists()


def test_checkpoint_records_agent_text_as_asserted_and_preserves_dirty_work(
    tmp_path: Path,
) -> None:
    root = _repository(tmp_path)
    (root / "scratch.txt").write_text("unfinished", encoding="utf-8")

    result = checkpoint_workspace(
        root,
        statement="The parser handles empty strings",
        next_action="Add property tests",
    )
    manifest = ProjectManifest.model_validate_json(
        (root / "threadline.json").read_text(encoding="utf-8")
    )

    assert result["epistemic_state"] == "ASSERTED"
    assert manifest.task.next_action == "Add property tests"
    assert manifest.observations[-1].statement == "The parser handles empty strings"
    assert manifest.observations[-1].state.value == "ASSERTED"
    assert result["worktree_paths_to_commit_together"] == [
        "scratch.txt",
        "threadline.json",
    ]
    assert set(git(root, "status", "--short").splitlines()) == {
        "M threadline.json",
        "?? scratch.txt",
    }

    with pytest.raises(ValueError, match="already has uncommitted changes"):
        checkpoint_workspace(
            root,
            statement="A second unreviewed claim",
            next_action="Do not overwrite the first checkpoint",
        )


def test_terminal_handoff_is_commit_bound_and_contains_inspectable_citations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("THREADLINE_DATABASE_URL", raising=False)
    root = _repository(tmp_path)
    checkpoint_workspace(
        root,
        statement="Whitespace behavior still needs an integration test",
        next_action="Add the whitespace integration test",
    )
    _commit(root, "threadline.json", message="Checkpoint parser continuation")
    synced = sync_local_workspace(root)

    rendered = render_handoff_markdown(synced.handoff.content)

    assert "# Threadline handoff" in rendered
    assert git(root, "rev-parse", "HEAD") in rendered
    assert "Add the whitespace integration test" in rendered
    assert "repo://" in rendered
    assert "ASSERTED" in rendered

    database_path = root / ".git" / "threadline" / "threadline.db"
    connection = sqlite3.connect(database_path)
    try:
        before = (
            connection.execute("SELECT COUNT(*) FROM context_entities").fetchone()[0],
            connection.execute("SELECT COUNT(*) FROM handoffs").fetchone()[0],
        )
    finally:
        connection.close()

    for _ in range(5):
        assert handoff_content(root) == synced.handoff.content

    connection = sqlite3.connect(database_path)
    try:
        after = (
            connection.execute("SELECT COUNT(*) FROM context_entities").fetchone()[0],
            connection.execute("SELECT COUNT(*) FROM handoffs").fetchone()[0],
        )
    finally:
        connection.close()
    assert after == before


def test_terminal_handoff_requires_explicit_sync_and_rejects_stale_head(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("THREADLINE_DATABASE_URL", raising=False)
    root = _repository(tmp_path)

    with pytest.raises(LookupError, match="run threadline sync first"):
        handoff_content(root)

    sync_local_workspace(root)
    (root / "parser.py").write_text(
        "def parse(value: str) -> str:\n    return value.strip().lower()\n",
        encoding="utf-8",
    )
    _commit(root, "parser.py", message="Change parser behavior")

    with pytest.raises(ValueError, match="compiled handoff is stale"):
        handoff_content(root)
