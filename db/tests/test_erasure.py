"""Section 11 of CLAUDE.md: erasing an account removes its links, and a match goes once it has no
owner left. The worker's `gc_match` job will run the statement below."""

import uuid

import pytest

from ma_db.testing import Connection, Factory, count

pytestmark = pytest.mark.db

ORPHANS = b"""
    DELETE FROM matches m
    WHERE NOT EXISTS (SELECT FROM user_matches o WHERE o.match_id = m.id)
"""


def rows(conn: Connection, table: str, column: str, value: object) -> int:
    return count(conn, f"SELECT count(*) FROM {table} WHERE {column} = %s", value)


def full_match(make: Factory) -> tuple[uuid.UUID, int]:
    match = make.match()
    player = make.player(match)
    make.metric(player)
    make.connection.execute(
        "INSERT INTO match_events (match_id, kind, frame, time_s, actor_player_id) "
        "VALUES (%s, 'goal', 1, 1.0, %s)",
        (match, player),
    )
    make.connection.execute(
        "INSERT INTO match_files (sha256, match_id) VALUES (%s, %s)", (str(match)[:32] * 2, match)
    )
    return match, player


def test_erasing_an_account_keeps_only_what_others_still_own(
    conn: Connection, make: Factory
) -> None:
    leaving, staying = make.user(), make.user()
    make.linked_account(leaving, "steam", "1")
    conn.execute(
        "INSERT INTO auth_sessions (token_hash, user_id, expires_at) "
        "VALUES ('\\x01', %s, now() + interval '1 day')",
        (leaving,),
    )
    conn.execute(
        "INSERT INTO player_claims (user_id, platform, platform_id) VALUES (%s, 'steam', '1')",
        (leaving,),
    )
    only_leaving, _ = full_match(make)
    shared, shared_player = full_match(make)
    only_staying, _ = full_match(make)
    make.user_match(only_leaving, user_id=leaving)
    make.user_match(shared, user_id=leaving)
    make.user_match(shared, user_id=staying)
    make.user_match(only_staying, user_id=staying)
    upload = make.upload(user_id=leaving, match_id=shared)
    kept_upload = make.upload(user_id=staying, match_id=shared)

    conn.execute("DELETE FROM users WHERE id = %s", (leaving,))

    # Every trace of the account is gone...
    for table in ("linked_accounts", "auth_sessions", "player_claims", "user_matches", "uploads"):
        assert rows(conn, table, "user_id", leaving) == 0, table
    assert rows(conn, "uploads", "id", upload) == 0
    # ...and until the cleanup runs, its matches still exist, without an owner.
    assert count(conn, "SELECT count(*) FROM matches WHERE id = %s", only_leaving) == 1

    conn.execute(ORPHANS)

    assert rows(conn, "matches", "id", only_leaving) == 0
    assert rows(conn, "matches", "id", shared) == 1
    assert rows(conn, "matches", "id", only_staying) == 1
    # The deleted match took everything of its own with it.
    for table in ("match_players", "match_events", "match_files"):
        assert rows(conn, table, "match_id", only_leaving) == 0, table
    # The shared match is intact for the other owner.
    assert rows(conn, "player_match_metrics", "match_player_id", shared_player) == 1
    assert rows(conn, "user_matches", "user_id", staying) == 2
    assert rows(conn, "uploads", "id", kept_upload) == 1


def test_metrics_of_a_deleted_match_go_with_it(conn: Connection, make: Factory) -> None:
    match, player = full_match(make)
    conn.execute("DELETE FROM matches WHERE id = %s", (match,))
    assert rows(conn, "player_match_metrics", "match_player_id", player) == 0


def test_team_metrics_of_a_deleted_match_go_with_it(conn: Connection, make: Factory) -> None:
    match = make.match()
    make.team_metric(match, 0)
    conn.execute("DELETE FROM matches WHERE id = %s", (match,))
    assert rows(conn, "team_match_metrics", "match_id", match) == 0


def test_an_upload_outlives_its_deleted_match(conn: Connection, make: Factory) -> None:
    match = make.match()
    upload = make.upload(user_id=make.user(), match_id=match)
    conn.execute("DELETE FROM matches WHERE id = %s", (match,))
    row = conn.execute("SELECT match_id FROM uploads WHERE id = %s", (upload,)).fetchone()
    assert row == (None,)


def test_an_expired_anonymous_session_takes_its_links_away(conn: Connection, make: Factory) -> None:
    session, user = make.anonymous_session(), make.user()
    alone, shared = make.match(), make.match()
    make.user_match(alone, anonymous_session_id=session)
    make.user_match(shared, anonymous_session_id=session)
    make.user_match(shared, user_id=user)
    make.upload(anonymous_session_id=session, match_id=alone)
    conn.execute(
        "INSERT INTO player_claims (anonymous_session_id, platform, platform_id) "
        "VALUES (%s, 'epic', 'abc')",
        (session,),
    )

    conn.execute("DELETE FROM anonymous_sessions WHERE id = %s", (session,))
    conn.execute(ORPHANS)

    assert rows(conn, "matches", "id", alone) == 0
    assert rows(conn, "matches", "id", shared) == 1
    assert rows(conn, "uploads", "anonymous_session_id", session) == 0
    assert rows(conn, "player_claims", "anonymous_session_id", session) == 0


def test_deleting_a_player_keeps_the_owner_and_the_event(conn: Connection, make: Factory) -> None:
    match = make.match()
    player = make.player(match)
    make.user_match(match, user_id=make.user())
    event = conn.execute(
        "INSERT INTO match_events (match_id, kind, frame, time_s, actor_player_id) "
        "VALUES (%s, 'goal', 1, 1.0, %s) RETURNING id",
        (match, player),
    ).fetchone()
    assert event is not None
    conn.execute("DELETE FROM match_players WHERE id = %s", (player,))
    # The match of the event stays: only the player's reference goes.
    row = conn.execute(
        "SELECT match_id, actor_player_id FROM match_events WHERE id = %s", (event[0],)
    ).fetchone()
    assert row == (match, None)
