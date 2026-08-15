from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from subprocess import CompletedProcess

import pytest
from tests.helpers import git

from threadline import client_verification
from threadline.client_profiles import connect_client
from threadline.client_verification import verify_client_connection
from threadline.manifest import initialize_manifest
from threadline.workspace import sync_local_workspace


def _repository(tmp_path: Path, name: str = "client-verification") -> Path:
    root = tmp_path / name
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "Repository Owner")
    git(root, "config", "user.email", "owner@example.invalid")
    (root / "service.py").write_text("def run() -> int:\n    return 1\n")
    git(root, "add", "service.py")
    git(root, "commit", "-m", "Add service")
    initialize_manifest(
        root,
        objective="Continue the service safely",
        next_action="Add a service integration test",
    )
    git(root, "add", "threadline.json")
    git(root, "commit", "-m", "Add Threadline context")
    sync_local_workspace(root)
    return root


def test_verify_client_requires_profile_then_performs_real_stdio_handshake(
    tmp_path: Path,
) -> None:
    root = _repository(tmp_path)

    missing = verify_client_connection(
        root,
        "antigravity",
        python_executable=Path(sys.executable),
    )
    assert missing["verified"] is False
    assert missing["profile"]["present"] is False

    connect_client(root, "antigravity", python_executable=Path(sys.executable))
    verified = verify_client_connection(
        root,
        "antigravity",
        python_executable=Path(sys.executable),
    )

    assert verified["verified"] is True
    assert verified["server"]["server"] == "Threadline"
    assert "get_task_context" in verified["server"]["tools"]
    assert verified["server"]["identity_matches"] is True
    assert verified["profile"]["server_key"].startswith("threadline-")
    assert verified["active_session"]["verified"] is None
    assert verified["native_client"]["verified"] is True


def test_antigravity_configuration_cannot_silently_point_at_another_repository(
    tmp_path: Path,
) -> None:
    first = _repository(tmp_path, "first-repository")
    second = _repository(tmp_path, "second-repository")
    first_connection = connect_client(
        first,
        "antigravity",
        python_executable=Path(sys.executable),
    )
    second_connection = connect_client(
        second,
        "antigravity",
        python_executable=Path(sys.executable),
    )

    assert first_connection["server_key"] != second_connection["server_key"]
    first_payload = json.loads((first / ".agents" / "mcp_config.json").read_text(encoding="utf-8"))
    second_target = second / ".agents" / "mcp_config.json"
    wrong_server = first_payload["mcpServers"][first_connection["server_key"]]
    second_target.write_text(
        json.dumps(
            {"mcpServers": {second_connection["server_key"]: wrong_server}},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    mismatched = verify_client_connection(
        second,
        "antigravity",
        python_executable=Path(sys.executable),
    )

    assert mismatched["verified"] is False
    assert mismatched["server"]["identity_matches"] is False
    assert (
        mismatched["server"]["identity"]["repository_id"]
        != mismatched["server"]["expected_identity"]["repository_id"]
    )

    connect_client(second, "antigravity", python_executable=Path(sys.executable))
    corrected = verify_client_connection(
        second,
        "antigravity",
        python_executable=Path(sys.executable),
    )
    corrected_payload = json.loads(second_target.read_text(encoding="utf-8"))

    assert corrected["verified"] is True
    assert corrected["server"]["identity_matches"] is True
    assert list(corrected_payload["mcpServers"]) == [second_connection["server_key"]]


def test_codex_verification_reports_trust_and_native_registration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _repository(tmp_path)
    connect_client(root, "codex", python_executable=Path(sys.executable))
    home = tmp_path / "home"
    config = home / ".codex" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text(
        f'[projects."{root}"]\ntrust_level = "trusted"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(
        "threadline.client_verification._codex_registration",
        lambda _root: {"verified": True, "reason": "registered"},
    )

    result = verify_client_connection(
        root,
        "codex",
        python_executable=Path(sys.executable),
    )

    assert result["verified"] is True
    assert result["trust"]["trusted"] is True
    assert result["native_client"]["verified"] is True


def test_client_verification_turns_handshake_failure_into_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _repository(tmp_path)
    connect_client(root, "antigravity", python_executable=Path(sys.executable))

    async def fail_probe(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise RuntimeError("server unavailable")

    monkeypatch.setattr("threadline.client_verification._probe_server", fail_probe)
    result = verify_client_connection(
        root,
        "antigravity",
        python_executable=Path(sys.executable),
    )

    assert result["verified"] is False
    assert "handshake failed" in result["server"]["reason"].lower()


@pytest.mark.parametrize(
    ("process", "expected"),
    [
        (CompletedProcess(["codex"], 1, "", "native failure"), "native failure"),
        (CompletedProcess(["codex"], 0, "not-json", ""), "unreadable"),
        (CompletedProcess(["codex"], 0, json.dumps([]), ""), "does not report"),
    ],
)
def test_codex_registration_failures_are_actionable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    process: CompletedProcess[str],
    expected: str,
) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: "/codex")
    monkeypatch.setattr(
        "threadline.client_verification.subprocess.run",
        lambda *_args, **_kwargs: process,
    )

    result = client_verification._codex_registration(tmp_path)

    assert result["verified"] is False
    assert expected in result["reason"]


def test_codex_trust_handles_malformed_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    config = home / ".codex" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text("[broken", encoding="utf-8")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

    trust = client_verification._codex_trust(tmp_path)

    assert trust["trusted"] is False
    assert "choose Trust" in trust["reason"]
