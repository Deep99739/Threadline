from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, cast

import pytest
from tests.helpers import git

from threadline.client_profiles import connect_client, disconnect_client
from threadline.git_hooks import install_refresh_hooks, uninstall_refresh_hooks
from threadline.manifest import ProjectManifest, initialize_manifest
from threadline.product_workflow import (
    advance_workspace,
    checkpoint_workspace,
    handoff_content,
    inspect_workspace,
    onboard_workspace,
    render_handoff_markdown,
    uninstall_workspace,
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


def test_first_handoff_orients_the_successor_to_repository_structure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("THREADLINE_DATABASE_URL", raising=False)
    root = _repository(tmp_path)
    (root / "tests").mkdir()
    (root / "tests" / "test_parser.py").write_text(
        "from parser import parse\n\n\ndef test_parse() -> None:\n    assert parse(' x ') == 'x'\n",
        encoding="utf-8",
    )
    _commit(root, "tests/test_parser.py", message="Add parser test")

    content = sync_local_workspace(root).handoff.content
    orientation = cast(dict[str, Any], content["repository_orientation"])

    assert orientation["tracked_text_files"] == 3
    assert orientation["parsed_code_files"] == 2
    assert orientation["languages"] == {"python": 2}
    assert orientation["test_files"] == ["tests/test_parser.py"]
    assert any(item["path"] == "tests" for item in orientation["top_level_areas"])
    rendered = render_handoff_markdown(content)
    assert "## Repository orientation" in rendered
    assert "tests/test_parser.py" in rendered


def test_advance_combines_check_and_handoff_update_without_self_certifying(
    tmp_path: Path,
) -> None:
    root = _repository(tmp_path)

    result = advance_workspace(
        root,
        statement="The parser handles surrounding whitespace",
        next_action="Add empty-input behavior",
        command=(sys.executable, "-c", "raise SystemExit(0)"),
        include_paths=("parser.py",),
        scope="FOCUSED",
    )
    manifest = ProjectManifest.model_validate_json(
        (root / "threadline.json").read_text(encoding="utf-8")
    )

    assert result["status"] == "PASSED"
    assert result["statement_state"] == "ASSERTED"
    assert manifest.task.next_action == "Add empty-input behavior"
    assert manifest.observations[-1].statement == "The parser handles surrounding whitespace"
    assert manifest.observations[-1].state.value == "ASSERTED"
    assert result["paths_to_commit_together"] == [
        "parser.py",
        "threadline.json",
        "threadline/test-report.json",
    ]


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

    disconnected = disconnect_client(root, "cursor")
    remaining = json.loads(target.read_text(encoding="utf-8"))
    assert disconnected["changed"] is True
    assert disconnected["preserved_other_servers"] is True
    assert remaining == {"mcpServers": {"existing": {"command": "existing-server"}}}


def test_codex_disconnect_preserves_other_sections_and_empty_profile_is_removed(
    tmp_path: Path,
) -> None:
    root = _repository(tmp_path)
    target = root / ".codex" / "config.toml"
    target.parent.mkdir()
    target.write_text('[model]\nname = "local"\n', encoding="utf-8")
    connect_client(root, "codex", python_executable=Path(sys.executable))

    result = disconnect_client(root, "codex")

    assert result["changed"] is True
    assert target.read_text(encoding="utf-8") == '[model]\nname = "local"\n'

    antigravity = root / ".agents" / "mcp_config.json"
    connect_client(root, "antigravity", python_executable=Path(sys.executable))
    removed = disconnect_client(root, "antigravity")
    assert removed["removed_file"] is True
    assert not antigravity.exists()


def test_disconnect_rejects_malformed_json_without_overwriting_it(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    target = root / ".cursor" / "mcp.json"
    target.parent.mkdir()
    target.write_text("[]\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not an object"):
        disconnect_client(root, "cursor")
    assert target.read_text(encoding="utf-8") == "[]\n"


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
    subprocess.run(
        ["git", "-C", str(root), "commit", "-m", "Normalize parser output"],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    deadline = time.monotonic() + 15
    refreshed = inspect_workspace(root)
    while not refreshed["ready"] and time.monotonic() < deadline:
        time.sleep(0.1)
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


def test_uninstall_removes_only_rebuildable_state_and_keeps_portable_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("THREADLINE_DATABASE_URL", raising=False)
    root = _repository(tmp_path)
    sync_local_workspace(root)
    connect_client(root, "antigravity", python_executable=Path(sys.executable))

    result = uninstall_workspace(root)

    assert result["contract_removed"] is False
    assert (root / "threadline.json").is_file()
    assert not (root / ".agents" / "mcp_config.json").exists()
    assert not (root / ".git" / "threadline" / "threadline.db").exists()
    assert git(root, "status", "--porcelain=v1", "--untracked-files=all") == ""


def test_uninstall_contract_removal_requires_clean_tree_and_leaves_reviewable_delete(
    tmp_path: Path,
) -> None:
    root = _repository(tmp_path)
    (root / "scratch.txt").write_text("work in progress\n", encoding="utf-8")
    with pytest.raises(ValueError, match="requires a clean working tree"):
        uninstall_workspace(root, remove_contract=True)

    (root / "scratch.txt").unlink()
    result = uninstall_workspace(root, remove_contract=True)
    assert result["contract_removed"] is True
    assert git(root, "status", "--short") == "D threadline.json"


def test_hook_uninstall_preserves_foreign_and_modified_hooks(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    install_refresh_hooks(root, python_executable=Path(sys.executable))
    post_commit = root / ".git" / "hooks" / "post-commit"
    post_commit.write_text(
        post_commit.read_text(encoding="utf-8") + "printf 'custom extension\\n'\n",
        encoding="utf-8",
    )
    post_merge = root / ".git" / "hooks" / "post-merge"
    post_merge.write_text("#!/bin/sh\nprintf 'foreign hook\\n'\n", encoding="utf-8")

    result = uninstall_refresh_hooks(root)

    assert result["blocked"] == ["post-commit"]
    assert result["preserved"] == ["post-merge"]
    assert set(result["removed"]) == {"post-checkout", "post-rewrite"}
    assert post_commit.is_file()
    assert post_merge.is_file()


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
