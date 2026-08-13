from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest
from tests.helpers import git

from threadline.cli import main
from threadline.command_evidence import run_and_record_check
from threadline.manifest import ProjectManifest, initialize_manifest
from threadline.product_workflow import checkpoint_workspace
from threadline.workspace import sync_local_workspace


def _repository(tmp_path: Path) -> Path:
    root = tmp_path / "checked-project"
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
        objective="Verify parser work before another agent continues",
        next_action="Run the complete parser check",
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


def _commit_record(root: Path) -> None:
    git(root, "add", "parser.py", "threadline.json", "threadline/test-report.json")
    git(
        root,
        "-c",
        "user.name=Repository Owner",
        "-c",
        "user.email=owner@example.invalid",
        "commit",
        "-m",
        "Record parser verification",
    )


def test_real_full_check_becomes_verified_only_after_commit_and_sync(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("THREADLINE_DATABASE_URL", raising=False)
    root = _repository(tmp_path)
    (root / "parser.py").write_text(
        "def parse(value: str) -> str:\n    return value.strip() or 'empty'\n",
        encoding="utf-8",
    )

    result = run_and_record_check(
        root,
        command=(sys.executable, "-c", "raise SystemExit(0)"),
        include_paths=("parser.py",),
        scope="FULL",
    )

    report_path = root / "threadline" / "test-report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    manifest = ProjectManifest.model_validate_json(
        (root / "threadline.json").read_text(encoding="utf-8")
    )
    expected_hash = hashlib.sha256((root / "parser.py").read_bytes()).hexdigest()
    assert result["status"] == "PASSED"
    assert report["exit_code"] == 0
    assert report["tested_content_hashes"]["parser.py"] == f"sha256:{expected_hash}"
    assert report["output_digest"].startswith("sha256:")
    assert "output" not in report
    assert any(item.kind == "test_report_scope" for item in manifest.verifiers)

    _commit_record(root)
    synchronized = sync_local_workspace(root)
    test_claim = next(
        item
        for item in synchronized.workspace.manifest.verifiers
        if item.kind == "test_report_scope"
    )
    verified = next(
        item
        for item in synchronized.handoff.context_pack.items
        if item.logical_key.startswith("claim:test_suite:all_tests_passed")
    )
    assert test_claim.path == "threadline/test-report.json"
    assert verified.epistemic_state.value == "VERIFIED"


def test_failed_check_is_recorded_as_failure_without_persisting_terminal_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("THREADLINE_DATABASE_URL", raising=False)
    root = _repository(tmp_path)
    secret_like_output = "TOKEN_SHOULD_NOT_ENTER_EVIDENCE"

    result = run_and_record_check(
        root,
        command=(
            sys.executable,
            "-c",
            f"print('{secret_like_output}'); raise SystemExit(3)",
        ),
        include_paths=("parser.py",),
        scope="FULL",
    )
    report_text = (root / "threadline" / "test-report.json").read_text(encoding="utf-8")

    assert result["status"] == "FAILED"
    assert result["exit_code"] == 3
    assert secret_like_output not in report_text
    _commit_record(root)
    synchronized = sync_local_workspace(root)
    contradicted = next(
        item
        for item in synchronized.handoff.context_pack.items
        if item.logical_key.startswith("claim:test_suite:all_tests_passed")
    )
    assert contradicted.epistemic_state.value == "CONTRADICTED"


def test_sensitive_command_arguments_are_redacted_from_the_report(tmp_path: Path) -> None:
    root = _repository(tmp_path)

    run_and_record_check(
        root,
        command=(
            sys.executable,
            "-c",
            "raise SystemExit(0)",
            "--api-key",
            "secret-value",
            "ACCESS_TOKEN=another-secret",
        ),
        include_paths=("parser.py",),
        scope="FOCUSED",
    )
    report_text = (root / "threadline" / "test-report.json").read_text(encoding="utf-8")

    assert "secret-value" not in report_text
    assert "another-secret" not in report_text
    assert report_text.count("[REDACTED]") == 2


def test_check_rejects_unsafe_paths_and_empty_commands(tmp_path: Path) -> None:
    root = _repository(tmp_path)

    with pytest.raises(ValueError, match="repository-relative"):
        run_and_record_check(
            root,
            command=(sys.executable, "-c", "raise SystemExit(0)"),
            include_paths=("../outside.py",),
            scope="FULL",
        )
    with pytest.raises(ValueError, match="command is required"):
        run_and_record_check(root, command=(), include_paths=("parser.py",), scope="FULL")


def test_checkpoint_and_check_can_be_reviewed_in_one_commit(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    checkpoint_workspace(
        root,
        statement="Whitespace handling is implemented",
        next_action="Commit the implementation and verification together",
    )

    result = run_and_record_check(
        root,
        command=(sys.executable, "-c", "raise SystemExit(0)"),
        include_paths=("parser.py",),
        scope="FULL",
    )

    assert result["status"] == "PASSED"
    manifest = ProjectManifest.model_validate_json(
        (root / "threadline.json").read_text(encoding="utf-8")
    )
    assert manifest.observations[-1].statement == "Whitespace handling is implemented"
    assert any(item.kind == "test_report_scope" for item in manifest.verifiers)
    assert set(git(root, "status", "--short", "--untracked-files=all").splitlines()) == {
        "M threadline.json",
        "?? threadline/test-report.json",
    }


def test_cli_check_accepts_a_command_after_the_standard_separator(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = _repository(tmp_path)

    main(
        [
            "check",
            str(root),
            "--include",
            "parser.py",
            "--scope",
            "FULL",
            "--",
            sys.executable,
            "-c",
            "raise SystemExit(0)",
        ]
    )
    result = json.loads(capsys.readouterr().out)

    assert result["status"] == "PASSED"
    assert result["raw_output_persisted"] is False


def test_check_does_not_forward_outer_coverage_instrumentation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _repository(tmp_path)
    monkeypatch.setenv("COVERAGE_PROCESS_START", "/private/coverage-config")
    monkeypatch.setenv("COV_CORE_SOURCE", "threadline")

    result = run_and_record_check(
        root,
        command=(
            sys.executable,
            "-c",
            (
                "import os; raise SystemExit("
                "'COVERAGE_PROCESS_START' in os.environ or 'COV_CORE_SOURCE' in os.environ)"
            ),
        ),
        include_paths=("parser.py",),
        scope="FOCUSED",
    )

    assert result["status"] == "PASSED"
