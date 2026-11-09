"""The migrations themselves, on an empty database."""

import psycopg
import pytest

from ma_db import cli, migrate
from ma_db.testing import temporary_database

pytestmark = pytest.mark.db

TABLES = {
    "alembic_version",
    "anonymous_sessions",
    "auth_sessions",
    "jobs",
    "linked_accounts",
    "match_events",
    "match_files",
    "match_players",
    "matches",
    "player_claims",
    "player_match_metrics",
    "rate_limit_buckets",
    "team_match_metrics",
    "uploads",
    "user_matches",
    "users",
}


def tables(url: str) -> set[str]:
    with psycopg.connect(url) as connection:
        rows = connection.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        ).fetchall()
    return {str(row[0]) for row in rows}


def test_upgrade_creates_every_table_on_an_empty_database(admin_url: str) -> None:
    with temporary_database(admin_url, migrated=False) as url:
        assert tables(url) == set()
        assert migrate.current(url) is None
        migrate.upgrade(url)
        assert tables(url) == TABLES
        assert migrate.current(url) == migrate.head()


def test_downgrade_removes_everything_and_upgrade_works_again(admin_url: str) -> None:
    with temporary_database(admin_url) as url:
        migrate.downgrade(url, "base")
        assert tables(url) == {"alembic_version"}
        assert migrate.current(url) is None
        migrate.upgrade(url)
        assert tables(url) == TABLES


def test_each_migration_goes_down_and_up_on_its_own(admin_url: str) -> None:
    with temporary_database(admin_url) as url:
        for revision in ("0004", "0003", "0002", "0001"):
            migrate.downgrade(url, revision)
            assert migrate.current(url) == revision
        migrate.upgrade(url)
        assert migrate.current(url) == migrate.head()


def test_upgrade_twice_changes_nothing(admin_url: str) -> None:
    with temporary_database(admin_url) as url:
        migrate.upgrade(url)
        assert tables(url) == TABLES


def test_the_command_line_upgrades_and_sets_passwords(
    admin_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    with temporary_database(admin_url, migrated=False) as url:
        monkeypatch.setenv("DATABASE_URL", url)
        monkeypatch.setenv("API_DB_PASSWORD", "it's a test")
        monkeypatch.delenv("WORKER_DB_PASSWORD", raising=False)
        assert cli.main(["upgrade"]) == 0
        assert migrate.current(url) == migrate.head()
        # The quote in the password shows the statement is composed safely.
        host = psycopg.conninfo.conninfo_to_dict(url)
        with psycopg.connect(
            host=host.get("host"),
            port=host.get("port"),
            dbname=host.get("dbname"),
            user="ma_api",
            password="it's a test",
        ) as connection:
            assert connection.execute("SELECT current_user").fetchone() == ("ma_api",)


def test_the_command_line_needs_a_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert cli.main(["current"]) == 2


def test_an_unknown_role_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown role"):
        migrate.set_role_password("postgresql://unused", "postgres", "x")
