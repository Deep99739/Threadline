"""Explicit schema migration entry points for local tools and deployment jobs."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config


def project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def migration_scripts_path() -> Path:
    """Return Alembic resources from the installed Threadline package."""

    return Path(__file__).resolve().parent / "migration_scripts"


def upgrade_database(database_url: str) -> None:
    config = Config()
    config.set_main_option("script_location", str(migration_scripts_path()))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
