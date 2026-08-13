from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from tests.helpers import git

from threadline.cli import main, run
from threadline.client_profiles import connect_client
from threadline.manifest import initialize_manifest
from threadline.workspace import sync_local_workspace


def _repository(tmp_path: Path) -> Path:
    root = tmp_path / "onboarding-cli"
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "Repository Owner")
    git(root, "config", "user.email", "owner@example.invalid")
    (root / "service.py").write_text("def run() -> int:\n    return 1\n")
    git(root, "add", "service.py")
    git(root, "commit", "-m", "Add service")
    initialize_manifest(root, objective="Continue safely", next_action="Add a test")
    git(root, "add", "threadline.json")
    git(root, "commit", "-m", "Add Threadline context")
    sync_local_workspace(root)
    return root


def test_cli_connect_verify_disconnect_and_uninstall_are_machine_readable(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = _repository(tmp_path)
    main(["connect", "antigravity", str(root), "--python-executable", sys.executable])
    assert json.loads(capsys.readouterr().out)["changed"] is True

    main(["verify-client", "antigravity", str(root), "--python-executable", sys.executable])
    assert json.loads(capsys.readouterr().out)["verified"] is True

    main(["disconnect", "antigravity", str(root)])
    assert json.loads(capsys.readouterr().out)["removed_file"] is True

    connect_client(root, "vscode", python_executable=Path(sys.executable))
    main(["uninstall", str(root)])
    result = json.loads(capsys.readouterr().out)
    assert result["contract_removed"] is False


def test_human_entry_point_prints_concise_expected_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "argv", ["threadline", "handoff", str(tmp_path)])
    with pytest.raises(SystemExit) as stopped:
        run()
    assert stopped.value.code == 2
    error = capsys.readouterr().err
    assert error.startswith("Threadline:")
    assert "Traceback" not in error
