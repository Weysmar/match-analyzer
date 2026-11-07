"""`apply_player_claims()`: a memorized player reaches the owner's other matches."""

import uuid

import pytest

from ma_db.testing import Connection, Factory

pytestmark = pytest.mark.db


def claim(
    conn: Connection,
    platform_id: str,
    *,
    user: uuid.UUID | None = None,
    session: uuid.UUID | None = None,
) -> None:
    conn.execute(
        "INSERT INTO player_claims (user_id, anonymous_session_id, platform, platform_id) "
        "VALUES (%s, %s, 'steam', %s)",
        (user, session, platform_id),
    )


def apply(conn: Connection, user: uuid.UUID | None, session: uuid.UUID | None) -> None:
    conn.execute("SELECT apply_player_claims(%s, %s)", (user, session))


def state(conn: Connection, link: int) -> tuple[int | None, str, bool]:
    row = conn.execute(
        "SELECT match_player_id, identity_source, verified FROM user_matches WHERE id = %s", (link,)
    ).fetchone()
    assert row is not None
    return row[0], row[1], row[2]


def test_a_user_finds_their_player_in_another_match(conn: Connection, make: Factory) -> None:
    user, match = make.user(), make.match()
    player = make.player(match, platform_id="1001")
    make.player(match, platform_id="1002")
    link = make.user_match(match, user_id=user)
    claim(conn, "1001", user=user)
    apply(conn, user, None)
    assert state(conn, link) == (player, "memorized", False)


def test_an_anonymous_session_too(conn: Connection, make: Factory) -> None:
    session, match = make.anonymous_session(), make.match()
    player = make.player(match, platform_id="1001")
    link = make.user_match(match, anonymous_session_id=session)
    claim(conn, "1001", session=session)
    apply(conn, None, session)
    assert state(conn, link) == (player, "memorized", False)


def test_a_match_without_that_player_stays_as_it_is(conn: Connection, make: Factory) -> None:
    user, match = make.user(), make.match()
    make.player(match, platform_id="1002")
    link = make.user_match(match, user_id=user)
    claim(conn, "1001", user=user)
    apply(conn, user, None)
    assert state(conn, link) == (None, "none", False)


def test_the_same_id_on_another_platform_is_someone_else(conn: Connection, make: Factory) -> None:
    user, match = make.user(), make.match()
    make.player(match, platform="epic", platform_id="1001")
    link = make.user_match(match, user_id=user)
    claim(conn, "1001", user=user)
    apply(conn, user, None)
    assert state(conn, link) == (None, "none", False)


def test_an_identity_already_there_is_kept(conn: Connection, make: Factory) -> None:
    user, match = make.user(), make.match()
    make.player(match, platform_id="1001")
    other = make.player(match, platform_id="1002")
    link = make.user_match(match, user_id=user, match_player_id=other, identity_source="claimed")
    claim(conn, "1001", user=user)
    apply(conn, user, None)
    assert state(conn, link) == (other, "claimed", False)


def test_someone_elses_claim_changes_nothing_for_me(conn: Connection, make: Factory) -> None:
    user, other, match = make.user(), make.user(), make.match()
    make.player(match, platform_id="1001")
    mine = make.user_match(match, user_id=user)
    claim(conn, "1001", user=other)
    apply(conn, user, None)
    apply(conn, other, None)
    assert state(conn, mine) == (None, "none", False)


def test_it_only_touches_this_owner(conn: Connection, make: Factory) -> None:
    user, other, match = make.user(), make.user(), make.match()
    make.player(match, platform_id="1001")
    theirs = make.user_match(match, user_id=other)
    claim(conn, "1001", user=user)
    claim(conn, "1001", user=other)
    apply(conn, user, None)
    assert state(conn, theirs) == (None, "none", False)


@pytest.mark.parametrize("role", ["ma_api", "ma_worker"])
def test_both_services_can_run_it(conn: Connection, make: Factory, role: str) -> None:
    user, match = make.user(), make.match()
    player = make.player(match, platform_id="1001")
    link = make.user_match(match, user_id=user)
    claim(conn, "1001", user=user)
    conn.execute(f"SET LOCAL ROLE {role}".encode())
    apply(conn, user, None)
    conn.execute(b"RESET ROLE")
    assert state(conn, link) == (player, "memorized", False)
