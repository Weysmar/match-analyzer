"""What the schema refuses by itself, whatever the code above it does."""

import hashlib

import psycopg.errors
import pytest

from ma_db.testing import Connection, Factory, count

pytestmark = pytest.mark.db

CHECK = psycopg.errors.CheckViolation
UNIQUE = psycopg.errors.UniqueViolation
FOREIGN_KEY = psycopg.errors.ForeignKeyViolation


def refuses(connection: Connection, error: type[Exception], query: str, *args: object) -> None:
    with pytest.raises(error), connection.transaction():
        connection.execute(query.encode(), args)


def test_a_provider_account_belongs_to_one_user(conn: Connection, make: Factory) -> None:
    first, second = make.user(), make.user()
    make.linked_account(first, "steam", "42")
    with pytest.raises(UNIQUE), conn.transaction():
        make.linked_account(second, "steam", "42")


def test_one_account_per_provider_for_a_user(conn: Connection, make: Factory) -> None:
    user = make.user()
    make.linked_account(user, "steam", "1")
    make.linked_account(user, "epic", "abc")
    with pytest.raises(UNIQUE), conn.transaction():
        make.linked_account(user, "steam", "2")


def test_unknown_providers_are_refused(conn: Connection, make: Factory) -> None:
    with pytest.raises(CHECK), conn.transaction():
        make.linked_account(make.user(), "psn", "1")


@pytest.mark.parametrize(
    "query",
    [
        "INSERT INTO player_claims (platform, platform_id) VALUES ('steam', '1')",
        "INSERT INTO user_matches (match_id) SELECT id FROM matches LIMIT 1",
        "INSERT INTO uploads (file_name, declared_size, incoming_key) VALUES ('a', 1, 'k')",
    ],
)
def test_a_row_without_an_owner_is_refused(conn: Connection, make: Factory, query: str) -> None:
    make.match()
    refuses(conn, CHECK, query)


def test_a_row_with_two_owners_is_refused(conn: Connection, make: Factory) -> None:
    user, session, match = make.user(), make.anonymous_session(), make.match()
    with pytest.raises(CHECK), conn.transaction():
        make.user_match(match, user_id=user, anonymous_session_id=session)
    with pytest.raises(CHECK), conn.transaction():
        make.upload(user_id=user, anonymous_session_id=session)


def test_an_owner_links_a_match_once(conn: Connection, make: Factory) -> None:
    user, session, match = make.user(), make.anonymous_session(), make.match()
    make.user_match(match, user_id=user)
    make.user_match(match, anonymous_session_id=session)
    with pytest.raises(UNIQUE), conn.transaction():
        make.user_match(match, user_id=user)
    with pytest.raises(UNIQUE), conn.transaction():
        make.user_match(match, anonymous_session_id=session)


def test_two_owners_can_share_a_match(make: Factory) -> None:
    match = make.match()
    make.user_match(match, user_id=make.user())
    make.user_match(match, user_id=make.user())


@pytest.mark.parametrize("source", ["none", "claimed", "memorized"])
def test_only_a_linked_account_verifies_a_match(
    conn: Connection, make: Factory, source: str
) -> None:
    match = make.match()
    player = None if source == "none" else make.player(match)
    with pytest.raises(CHECK), conn.transaction():
        make.user_match(
            match,
            user_id=make.user(),
            match_player_id=player,
            identity_source=source,
            verified=True,
        )


def test_a_linked_account_can_verify_a_match(make: Factory) -> None:
    match = make.match()
    make.user_match(
        match,
        user_id=make.user(),
        match_player_id=make.player(match),
        identity_source="linked_account",
        verified=True,
    )


def test_an_identity_needs_a_player_and_the_reverse(conn: Connection, make: Factory) -> None:
    match = make.match()
    with pytest.raises(CHECK), conn.transaction():
        make.user_match(match, user_id=make.user(), identity_source="claimed")
    with pytest.raises(CHECK), conn.transaction():
        make.user_match(match, user_id=make.user(), match_player_id=make.player(match))


def test_a_player_of_another_match_cannot_be_chosen(conn: Connection, make: Factory) -> None:
    match, other = make.match(), make.match()
    player = make.player(other)
    with pytest.raises(FOREIGN_KEY), conn.transaction():
        make.user_match(
            match, user_id=make.user(), match_player_id=player, identity_source="claimed"
        )


def test_an_event_cannot_name_a_player_of_another_match(conn: Connection, make: Factory) -> None:
    match, other = make.match(), make.match()
    refuses(
        conn,
        FOREIGN_KEY,
        "INSERT INTO match_events (match_id, kind, frame, time_s, actor_player_id) "
        "VALUES (%s, 'goal', 1, 1.0, %s)",
        match,
        make.player(other),
    )


def test_matches_are_unique_by_their_key(conn: Connection) -> None:
    key = hashlib.sha256(b"same").hexdigest()
    query = "INSERT INTO matches (dedupe_key, parser_version) VALUES (%s, '0.1.1')"
    conn.execute(query, (key,))
    refuses(conn, UNIQUE, query, key)


def test_a_file_belongs_to_one_match(conn: Connection, make: Factory) -> None:
    sha = hashlib.sha256(b"file").hexdigest()
    query = "INSERT INTO match_files (sha256, match_id) VALUES (%s, %s)"
    conn.execute(query, (sha, make.match()))
    refuses(conn, UNIQUE, query, sha, make.match())


@pytest.mark.parametrize(
    ("column", "value"),
    [("status", "lost"), ("played_at_source", "guess")],
)
def test_match_values_are_checked(conn: Connection, column: str, value: str) -> None:
    key = hashlib.sha256(column.encode()).hexdigest()
    refuses(
        conn,
        CHECK,
        f"INSERT INTO matches (dedupe_key, parser_version, {column}) VALUES (%s, '0.1.1', %s)",
        key,
        value,
    )


@pytest.mark.parametrize(("column", "value"), [("platform", "stadia"), ("team", "-1")])
def test_player_values_are_checked(
    conn: Connection, make: Factory, column: str, value: str
) -> None:
    row = {"platform": "steam", "team": "0", column: value}
    refuses(
        conn,
        CHECK,
        "INSERT INTO match_players (match_id, platform, display_name, team) "
        "VALUES (%s, %s, 'a', %s::smallint)",
        make.match(),
        row["platform"],
        row["team"],
    )


def test_a_rejected_upload_says_why(conn: Connection, make: Factory) -> None:
    upload = make.upload(user_id=make.user())
    refuses(conn, CHECK, "UPDATE uploads SET status = 'rejected' WHERE id = %s", upload)
    refuses(conn, CHECK, "UPDATE uploads SET rejection = 'corrupt' WHERE id = %s", upload)
    conn.execute(
        "UPDATE uploads SET status = 'rejected', rejection = 'corrupt' WHERE id = %s", (upload,)
    )
    assert count(conn, "SELECT count(*) FROM uploads WHERE rejection = 'corrupt'") == 1


def test_a_metric_is_stored_once_per_player(conn: Connection, make: Factory) -> None:
    player = make.player(make.match())
    make.metric(player)
    with pytest.raises(UNIQUE), conn.transaction():
        make.metric(player)
    make.metric(player, "boost.pct_zero")


def test_a_metric_can_be_undefined(conn: Connection, make: Factory) -> None:
    conn.execute(
        "INSERT INTO player_match_metrics (match_player_id, metric_id, value, analysis_version) "
        "VALUES (%s, 'pos.pct_last_back', NULL, '1')",
        (make.player(make.match()),),
    )


def test_job_kinds_and_statuses_are_checked(conn: Connection) -> None:
    refuses(conn, CHECK, "INSERT INTO jobs (kind) VALUES ('mine_bitcoin')")
    refuses(conn, CHECK, "INSERT INTO jobs (kind, status) VALUES ('parse', 'lost')")
