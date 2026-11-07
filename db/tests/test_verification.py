"""`refresh_verification()`: when a match counts as verified."""

import uuid

import pytest

from ma_db.testing import Connection, Factory

pytestmark = pytest.mark.db


def refresh(conn: Connection, user: uuid.UUID) -> None:
    conn.execute("SELECT refresh_verification(%s)", (user,))


def state(conn: Connection, link: int) -> tuple[int | None, str, bool]:
    row = conn.execute(
        "SELECT match_player_id, identity_source, verified FROM user_matches WHERE id = %s", (link,)
    ).fetchone()
    assert row is not None
    return row[0], row[1], row[2]


def test_the_players_id_is_the_accounts(conn: Connection, make: Factory) -> None:
    user, match = make.user(), make.match()
    make.linked_account(user, "steam", "1001")
    player = make.player(match, platform="steam", platform_id="1001")
    make.player(match, platform="steam", platform_id="1002")
    link = make.user_match(match, user_id=user)
    refresh(conn, user)
    assert state(conn, link) == (player, "linked_account", True)


def test_no_player_has_the_accounts_id(conn: Connection, make: Factory) -> None:
    user, match = make.user(), make.match()
    make.linked_account(user, "steam", "1001")
    make.player(match, platform="steam", platform_id="1002")
    link = make.user_match(match, user_id=user)
    refresh(conn, user)
    assert state(conn, link) == (None, "none", False)


def test_the_same_id_on_another_platform_proves_nothing(conn: Connection, make: Factory) -> None:
    user, match = make.user(), make.match()
    make.linked_account(user, "steam", "1001")
    make.player(match, platform="epic", platform_id="1001")
    link = make.user_match(match, user_id=user)
    refresh(conn, user)
    assert state(conn, link) == (None, "none", False)


def test_someone_elses_account_proves_nothing(conn: Connection, make: Factory) -> None:
    user, other, match = make.user(), make.user(), make.match()
    make.linked_account(other, "steam", "1001")
    make.player(match, platform="steam", platform_id="1001")
    link = make.user_match(match, user_id=user)
    refresh(conn, user)
    assert state(conn, link) == (None, "none", False)


def test_a_player_without_an_id_proves_nothing(conn: Connection, make: Factory) -> None:
    user, match = make.user(), make.match()
    make.linked_account(user, "epic", "abc")
    conn.execute(
        "INSERT INTO match_players (match_id, platform, platform_id, display_name, team) "
        "VALUES (%s, 'epic', NULL, 'a player', 0)",
        (match,),
    )
    link = make.user_match(match, user_id=user)
    refresh(conn, user)
    assert state(conn, link) == (None, "none", False)


@pytest.mark.parametrize("source", ["claimed", "memorized"])
def test_an_unproven_identity_stays_as_it_is(conn: Connection, make: Factory, source: str) -> None:
    user, match = make.user(), make.match()
    make.linked_account(user, "steam", "1001")
    player = make.player(match, platform="steam", platform_id="1002")
    link = make.user_match(match, user_id=user, match_player_id=player, identity_source=source)
    refresh(conn, user)
    assert state(conn, link) == (player, source, False)


def test_the_proof_wins_over_a_claim(conn: Connection, make: Factory) -> None:
    user, match = make.user(), make.match()
    make.linked_account(user, "steam", "1001")
    mine = make.player(match, platform="steam", platform_id="1001")
    claimed = make.player(match, platform="steam", platform_id="1002")
    link = make.user_match(match, user_id=user, match_player_id=claimed, identity_source="claimed")
    refresh(conn, user)
    assert state(conn, link) == (mine, "linked_account", True)


def test_losing_the_proof_loses_the_verification(conn: Connection, make: Factory) -> None:
    user, match = make.user(), make.match()
    player = make.player(match, platform="steam", platform_id="1001")
    link = make.user_match(
        match, user_id=user, match_player_id=player, identity_source="linked_account", verified=True
    )
    refresh(conn, user)
    assert state(conn, link) == (None, "none", False)


def test_two_of_ones_accounts_in_one_match_settle_on_one_player(
    conn: Connection, make: Factory
) -> None:
    user, match = make.user(), make.match()
    make.linked_account(user, "steam", "1001")
    make.linked_account(user, "epic", "abc")
    first = make.player(match, platform="steam", platform_id="1001")
    make.player(match, platform="epic", platform_id="abc")
    link = make.user_match(match, user_id=user)
    refresh(conn, user)
    assert state(conn, link) == (first, "linked_account", True)


def test_it_only_touches_this_user(conn: Connection, make: Factory) -> None:
    user, other, match = make.user(), make.user(), make.match()
    make.linked_account(other, "steam", "1001")
    make.player(match, platform="steam", platform_id="1001")
    link = make.user_match(match, user_id=other)
    refresh(conn, user)
    assert state(conn, link) == (None, "none", False)


def test_it_leaves_anonymous_sessions_alone(conn: Connection, make: Factory) -> None:
    user, match = make.user(), make.match()
    make.linked_account(user, "steam", "1001")
    make.player(match, platform="steam", platform_id="1001")
    link = make.user_match(match, anonymous_session_id=make.anonymous_session())
    refresh(conn, user)
    assert state(conn, link) == (None, "none", False)


@pytest.mark.parametrize("role", ["ma_api", "ma_worker"])
def test_both_services_can_run_it(conn: Connection, make: Factory, role: str) -> None:
    user, match = make.user(), make.match()
    make.linked_account(user, "steam", "1001")
    player = make.player(match, platform="steam", platform_id="1001")
    link = make.user_match(match, user_id=user)
    conn.execute(f"SET LOCAL ROLE {role}".encode())
    refresh(conn, user)
    conn.execute(b"RESET ROLE")
    assert state(conn, link) == (player, "linked_account", True)
