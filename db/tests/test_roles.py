"""The API and the worker can do what they need, and nothing else."""

import psycopg.errors
import pytest

from ma_db.testing import Connection, Factory

pytestmark = pytest.mark.db

DENIED = psycopg.errors.InsufficientPrivilege


def as_role(connection: Connection, role: str, query: str, *args: object) -> None:
    """Runs `query` as `role`. Anything that happened stays in this savepoint's scope."""
    with connection.transaction():
        connection.execute(f"SET LOCAL ROLE {role}".encode())
        connection.execute(query.encode(), args)
        connection.execute(b"RESET ROLE")


def denied(connection: Connection, role: str, query: str, *args: object) -> None:
    with pytest.raises(DENIED):
        as_role(connection, role, query, *args)


@pytest.mark.parametrize(
    "query",
    [
        "UPDATE matches SET status = 'failed'",
        "DELETE FROM matches",
        "INSERT INTO matches (dedupe_key, parser_version) VALUES ('x', '1')",
        "UPDATE match_players SET display_name = 'x'",
        "DELETE FROM match_players",
        "UPDATE player_match_metrics SET value = 0",
        "UPDATE team_match_metrics SET value = 0",
        "SELECT * FROM match_files",
        "SELECT * FROM jobs",
        "UPDATE jobs SET status = 'dead'",
        "DELETE FROM jobs",
        "CREATE TABLE mine (id int)",
        "DROP TABLE users",
    ],
)
def test_the_api_cannot_do_the_workers_job(conn: Connection, query: str) -> None:
    denied(conn, "ma_api", query)


@pytest.mark.parametrize(
    "query",
    [
        "INSERT INTO users (display_name) VALUES ('x')",
        "UPDATE users SET display_name = 'x'",
        "DELETE FROM users",
        "UPDATE linked_accounts SET display_name = 'x'",
        "DELETE FROM linked_accounts",
        "INSERT INTO player_claims (user_id, platform, platform_id) VALUES (NULL, 'steam', '1')",
        "INSERT INTO uploads (file_name, declared_size, incoming_key) VALUES ('a', 1, 'k')",
        "UPDATE auth_sessions SET expires_at = now()",
        "INSERT INTO rate_limit_buckets (bucket_key, window_start) VALUES ('a', now())",
        "CREATE TABLE mine (id int)",
        "DROP TABLE matches",
    ],
)
def test_the_worker_cannot_touch_accounts(conn: Connection, query: str) -> None:
    denied(conn, "ma_worker", query)


def test_the_api_does_its_job(conn: Connection, make: Factory) -> None:
    match = make.match()
    player = make.player(match)
    as_role(conn, "ma_api", "INSERT INTO users (display_name) VALUES ('x')")
    as_role(conn, "ma_api", "SELECT * FROM matches, match_players, match_events")
    as_role(conn, "ma_api", "SELECT * FROM player_match_metrics, team_match_metrics")
    as_role(conn, "ma_api", "INSERT INTO jobs (kind) VALUES ('parse')")
    as_role(
        conn,
        "ma_api",
        "INSERT INTO rate_limit_buckets (bucket_key, window_start) VALUES ('a', now())",
    )
    as_role(
        conn,
        "ma_api",
        "INSERT INTO user_matches (user_id, match_id, match_player_id, identity_source) "
        "VALUES (%s, %s, %s, 'claimed')",
        make.user(),
        match,
        player,
    )
    as_role(
        conn,
        "ma_api",
        "INSERT INTO uploads (user_id, file_name, declared_size, incoming_key) "
        "VALUES (%s, 'a', 1, 'k')",
        make.user(),
    )


def test_the_api_erases_an_account_with_its_links(conn: Connection, make: Factory) -> None:
    user = make.user()
    match = make.match()
    make.user_match(match, user_id=user)
    make.linked_account(user, "steam", "1")
    as_role(conn, "ma_api", "DELETE FROM users WHERE id = %s", user)


def test_the_worker_does_its_job(conn: Connection, make: Factory) -> None:
    as_role(
        conn,
        "ma_worker",
        "INSERT INTO matches (dedupe_key, parser_version) VALUES ('k', '0.1.1')",
    )
    match = make.match()
    upload = make.upload(user_id=make.user())
    as_role(
        conn,
        "ma_worker",
        "INSERT INTO match_players (match_id, platform, display_name, team) "
        "VALUES (%s, 'steam', 'a', 0)",
        match,
    )
    as_role(
        conn,
        "ma_worker",
        "INSERT INTO match_events (match_id, kind, frame, time_s) VALUES (%s, 'goal', 1, 1.0)",
        match,
    )
    as_role(conn, "ma_worker", "INSERT INTO match_files (sha256, match_id) VALUES ('s', %s)", match)
    as_role(conn, "ma_worker", "UPDATE uploads SET status = 'processing' WHERE id = %s", upload)
    as_role(conn, "ma_worker", "INSERT INTO jobs (kind) VALUES ('analyze')")
    as_role(conn, "ma_worker", "UPDATE jobs SET status = 'done'")
    as_role(conn, "ma_worker", "SELECT * FROM linked_accounts, player_claims")
    as_role(conn, "ma_worker", "DELETE FROM anonymous_sessions WHERE expires_at < now()")
    as_role(conn, "ma_worker", "DELETE FROM auth_sessions WHERE expires_at < now()")
    as_role(conn, "ma_worker", "DELETE FROM rate_limit_buckets")
    as_role(conn, "ma_worker", "DELETE FROM matches WHERE id = %s", match)
