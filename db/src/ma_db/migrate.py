"""Applies the migrations and sets the passwords of the roles."""

from pathlib import Path

import psycopg
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg import sql

MIGRATIONS = Path(__file__).parent / "migrations"
ROLES = ("ma_api", "ma_worker")


def _config(url: str) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    config.set_main_option("path_separator", "os")
    # SQLAlchemy needs to be told which driver to use.
    config.attributes["url"] = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return config


def upgrade(url: str, revision: str = "head") -> None:
    command.upgrade(_config(url), revision)


def downgrade(url: str, revision: str) -> None:
    command.downgrade(_config(url), revision)


def head() -> str | None:
    return ScriptDirectory.from_config(_config("postgresql://unused")).get_current_head()


def current(url: str) -> str | None:
    """The revision this database is at, `None` before the first migration."""
    with psycopg.connect(url) as connection:
        exists = connection.execute(
            "SELECT to_regclass('public.alembic_version') IS NOT NULL"
        ).fetchone()
        if exists is None or not exists[0]:
            return None
        row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        return None if row is None else str(row[0])


def set_role_password(url: str, role: str, password: str) -> None:
    """`ALTER ROLE` takes no bound parameter: the composition quotes both values."""
    if role not in ROLES:
        raise ValueError(f"unknown role: {role}")
    statement = sql.SQL("ALTER ROLE {} PASSWORD {}").format(
        sql.Identifier(role), sql.Literal(password)
    )
    with psycopg.connect(url) as connection:
        connection.execute(statement)
