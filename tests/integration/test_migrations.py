from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from tests.helpers import PROJECT_ROOT


def migration_config(database_url: str) -> Config:
    config = Config(PROJECT_ROOT / "alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def test_initial_migration_upgrades_and_downgrades(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("THREADLINE_DATABASE_URL", raising=False)
    database_url = f"sqlite+pysqlite:///{tmp_path / 'migration.db'}"
    config = migration_config(database_url)

    command.upgrade(config, "head")
    engine = sa.create_engine(database_url)
    tables = set(sa.inspect(engine).get_table_names())
    assert {
        "alembic_version",
        "context_entities",
        "evidence_content",
        "handoffs",
        "repositories",
    }.issubset(tables)

    command.downgrade(config, "base")
    assert set(sa.inspect(engine).get_table_names()) == {"alembic_version"}
    engine.dispose()
