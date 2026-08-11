from __future__ import annotations

import json
from pathlib import Path

import pytest

from threadline.cli import _database_url, main
from threadline.demo import prepare_demo_repository, run_demo


def test_prepare_demo_is_repeatable_but_will_not_overwrite_unknown_data(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "demo"
    assert prepare_demo_repository(destination) == destination.resolve()
    assert prepare_demo_repository(destination) == destination.resolve()

    occupied = tmp_path / "occupied"
    occupied.mkdir()
    with pytest.raises(FileExistsError, match="not a Git repository"):
        prepare_demo_repository(occupied)


def test_run_demo_uses_real_ingestion_and_compilation(tmp_path: Path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'demo.db'}"

    result = run_demo(database_url, tmp_path / "demo-repository")

    assert result.handoff.content["contradictions"]
    assert result.handoff.content["unknowns"]
    assert result.handoff.context_pack.items
    assert any(item.citations for item in result.handoff.context_pack.items)


def test_cli_commands_emit_machine_readable_demo(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repository = tmp_path / "cli-demo"
    database_url = f"sqlite+pysqlite:///{tmp_path / 'cli.db'}"

    main(["prepare-demo", "--repository", str(repository)])
    assert Path(capsys.readouterr().out.strip()) == repository

    main(["migrate", "--database-url", database_url])
    assert capsys.readouterr().out.strip() == "Threadline schema is current."

    main(
        [
            "demo",
            "--database-url",
            database_url,
            "--repository",
            str(repository),
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["repository"] == str(repository.resolve())
    assert payload["contradictions"]
    assert payload["context_pack"]["items"]


def test_database_url_prefers_explicit_then_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("THREADLINE_DATABASE_URL", "sqlite:///environment.db")
    assert _database_url("sqlite:///explicit.db") == "sqlite:///explicit.db"
    assert _database_url(None) == "sqlite:///environment.db"
