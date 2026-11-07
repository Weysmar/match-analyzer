"""What signing in does to the matches of an anonymous session (D5), and verification."""

import uuid

import pytest
from fastapi.testclient import TestClient

from ma_api import account
from ma_api.settings import Settings
from ma_db.testing import Connection, Factory, count

from .helpers import (
    ME,
    STEAM_IDS,
    FakeProviders,
    anonymous_session,
    assert_failed,
    browser_for,
    steam_sign_in,
    user_session,
)

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_limits")]

SITE = "http://testserver"


def link_of(conn: Connection, user_id: str, match: uuid.UUID) -> tuple[int | None, str, bool]:
    row = conn.execute(
        "SELECT match_player_id, identity_source, verified FROM user_matches "
        "WHERE user_id = %s AND match_id = %s",
        (user_id, match),
    ).fetchone()
    assert row is not None
    return row[0], row[1], row[2]


def signed_in_user(browser: TestClient) -> str:
    user: str = browser.get(ME).json()["user"]["id"]
    return user


def test_a_match_of_mine_comes_along_verified(
    browser: TestClient, conn: Connection, make: Factory
) -> None:
    steam_id = next(STEAM_IDS)
    session, token = anonymous_session(conn)
    match = make.match()
    player = make.player(match, platform="steam", platform_id=steam_id)
    make.user_match(match, anonymous_session_id=session)
    browser.cookies.set("anon", token)
    steam_sign_in(browser, steam_id)
    assert link_of(conn, signed_in_user(browser), match) == (player, "linked_account", True)


def test_a_match_i_claimed_with_my_real_id_is_verified(
    browser: TestClient, conn: Connection, make: Factory
) -> None:
    steam_id = next(STEAM_IDS)
    session, token = anonymous_session(conn)
    match = make.match()
    player = make.player(match, platform="steam", platform_id=steam_id)
    make.user_match(
        match, anonymous_session_id=session, match_player_id=player, identity_source="claimed"
    )
    browser.cookies.set("anon", token)
    steam_sign_in(browser, steam_id)
    assert link_of(conn, signed_in_user(browser), match) == (player, "linked_account", True)


def test_a_match_without_me_comes_along_unverified(
    browser: TestClient, conn: Connection, make: Factory
) -> None:
    """Someone else's replay, claimed as theirs: kept and labelled, never verified (D5)."""
    session, token = anonymous_session(conn)
    match = make.match()
    claimed = make.player(match, platform="steam", platform_id=next(STEAM_IDS))
    make.user_match(
        match, anonymous_session_id=session, match_player_id=claimed, identity_source="claimed"
    )
    browser.cookies.set("anon", token)
    steam_sign_in(browser, next(STEAM_IDS))
    assert link_of(conn, signed_in_user(browser), match) == (claimed, "claimed", False)


def test_the_anonymous_session_ends(browser: TestClient, conn: Connection, make: Factory) -> None:
    session, token = anonymous_session(conn)
    make.user_match(make.match(), anonymous_session_id=session)
    browser.cookies.set("anon", token)
    response = steam_sign_in(browser, next(STEAM_IDS))
    assert any(c.startswith('anon=""') for c in response.headers.get_list("set-cookie"))
    assert count(conn, "SELECT count(*) FROM anonymous_sessions WHERE id = %s", session) == 0
    assert (
        count(conn, "SELECT count(*) FROM user_matches WHERE anonymous_session_id = %s", session)
        == 0
    )


def test_uploads_and_memorized_players_come_along(
    browser: TestClient, conn: Connection, make: Factory
) -> None:
    session, token = anonymous_session(conn)
    upload = make.upload(anonymous_session_id=session)
    conn.execute(
        "INSERT INTO player_claims (anonymous_session_id, platform, platform_id) "
        "VALUES (%s, 'psn', 'a-claim')",
        (session,),
    )
    browser.cookies.set("anon", token)
    steam_sign_in(browser, next(STEAM_IDS))
    user = signed_in_user(browser)
    assert (
        count(conn, "SELECT count(*) FROM uploads WHERE id = %s AND user_id = %s", upload, user)
        == 1
    )
    assert (
        count(
            conn,
            "SELECT count(*) FROM player_claims WHERE user_id = %s AND platform_id = 'a-claim'",
            user,
        )
        == 1
    )


def test_a_match_i_already_have_keeps_my_link(
    browser: TestClient, conn: Connection, make: Factory
) -> None:
    steam_id = next(STEAM_IDS)
    steam_sign_in(browser, steam_id)
    user = signed_in_user(browser)
    match = make.match()
    other = make.player(match, platform="epic", platform_id="someone")
    make.user_match(match, user_id=uuid.UUID(user))
    session, token = anonymous_session(conn)
    make.user_match(
        match, anonymous_session_id=session, match_player_id=other, identity_source="claimed"
    )
    browser.cookies.set("anon", token)
    steam_sign_in(browser, steam_id)
    # One link only, which took the identity chosen meanwhile, and nothing verified by it.
    assert count(conn, "SELECT count(*) FROM user_matches WHERE match_id = %s", match) == 1
    assert link_of(conn, user, match) == (other, "claimed", False)


def test_an_identity_i_already_chose_is_not_replaced(
    browser: TestClient, conn: Connection, make: Factory
) -> None:
    steam_id = next(STEAM_IDS)
    steam_sign_in(browser, steam_id)
    user = signed_in_user(browser)
    match = make.match()
    mine = make.player(match, platform="epic", platform_id="me-maybe")
    other = make.player(match, platform="epic", platform_id="someone")
    make.user_match(match, user_id=uuid.UUID(user), match_player_id=mine, identity_source="claimed")
    session, token = anonymous_session(conn)
    make.user_match(
        match, anonymous_session_id=session, match_player_id=other, identity_source="claimed"
    )
    browser.cookies.set("anon", token)
    steam_sign_in(browser, steam_id)
    assert link_of(conn, user, match) == (mine, "claimed", False)


def test_an_expired_session_does_not_come_along(
    browser: TestClient, conn: Connection, make: Factory
) -> None:
    session, token = anonymous_session(conn, valid=False)
    match = make.match()
    make.user_match(match, anonymous_session_id=session)
    browser.cookies.set("anon", token)
    steam_sign_in(browser, next(STEAM_IDS))
    assert (
        count(conn, "SELECT count(*) FROM user_matches WHERE anonymous_session_id = %s", session)
        == 1
    )


def test_a_failed_link_leaves_the_session_alone(
    browser: TestClient,
    settings: Settings,
    providers: FakeProviders,
    conn: Connection,
    make: Factory,
) -> None:
    taken = next(STEAM_IDS)
    with browser_for(settings, providers) as other:
        steam_sign_in(other, taken)
    steam_sign_in(browser, next(STEAM_IDS))
    session, token = anonymous_session(conn)
    make.user_match(make.match(), anonymous_session_id=session)
    browser.cookies.set("anon", token)
    assert_failed(steam_sign_in(browser, taken), SITE, "account_already_linked")
    assert (
        count(conn, "SELECT count(*) FROM user_matches WHERE anonymous_session_id = %s", session)
        == 1
    )


def test_other_sessions_stay_where_they_are(
    browser: TestClient, conn: Connection, make: Factory
) -> None:
    mine, token = anonymous_session(conn)
    theirs, _ = anonymous_session(conn)
    make.user_match(make.match(), anonymous_session_id=mine)
    make.user_match(make.match(), anonymous_session_id=theirs)
    browser.cookies.set("anon", token)
    steam_sign_in(browser, next(STEAM_IDS))
    assert (
        count(conn, "SELECT count(*) FROM user_matches WHERE anonymous_session_id = %s", theirs)
        == 1
    )
    assert count(conn, "SELECT count(*) FROM anonymous_sessions WHERE id = %s", theirs) == 1


def test_linking_an_account_verifies_my_existing_matches(
    browser: TestClient, conn: Connection, make: Factory
) -> None:
    user = make.user()
    make.linked_account(user, "epic", "my-epic-account")
    match = make.match()
    player = make.player(match, platform="steam", platform_id=(steam_id := next(STEAM_IDS)))
    make.user_match(match, user_id=user)
    browser.cookies.set("session", user_session(conn, user))
    steam_sign_in(browser, steam_id)
    assert link_of(conn, str(user), match) == (player, "linked_account", True)


def test_signing_in_refreshes_what_was_parsed_since(
    browser: TestClient, conn: Connection, make: Factory
) -> None:
    steam_id = next(STEAM_IDS)
    steam_sign_in(browser, steam_id)
    user = signed_in_user(browser)
    browser.cookies.clear()
    match = make.match()
    player = make.player(match, platform="steam", platform_id=steam_id)
    make.user_match(match, user_id=uuid.UUID(user))
    steam_sign_in(browser, steam_id)
    assert link_of(conn, user, match) == (player, "linked_account", True)


def set_player_name(conn: Connection, player: int, name: str, *, anonymized: bool = False) -> None:
    conn.execute(
        "UPDATE match_players SET display_name = %s, anonymized = %s WHERE id = %s",
        (name, anonymized, player),
    )


def test_an_account_takes_its_name_from_a_verified_replay(
    browser: TestClient, conn: Connection, make: Factory
) -> None:
    steam_id = next(STEAM_IDS)
    session, token = anonymous_session(conn)
    match = make.match()
    player = make.player(match, platform="steam", platform_id=steam_id)
    set_player_name(conn, player, "My own name")
    make.user_match(match, anonymous_session_id=session)
    browser.cookies.set("anon", token)
    steam_sign_in(browser, steam_id)
    assert browser.get(ME).json()["user"]["display_name"] == "My own name"


def test_a_name_hidden_in_the_game_is_not_taken(
    browser: TestClient, conn: Connection, make: Factory
) -> None:
    steam_id = next(STEAM_IDS)
    session, token = anonymous_session(conn)
    match = make.match()
    player = make.player(match, platform="steam", platform_id=steam_id)
    set_player_name(conn, player, "Hidden", anonymized=True)
    make.user_match(match, anonymous_session_id=session)
    browser.cookies.set("anon", token)
    steam_sign_in(browser, steam_id)
    assert browser.get(ME).json()["user"]["display_name"] == account.DEFAULT_DISPLAY_NAME


def test_a_claimed_replay_gives_no_name(
    browser: TestClient, conn: Connection, make: Factory
) -> None:
    session, token = anonymous_session(conn)
    match = make.match()
    claimed = make.player(match, platform="steam", platform_id=next(STEAM_IDS))
    set_player_name(conn, claimed, "Someone else")
    make.user_match(
        match, anonymous_session_id=session, match_player_id=claimed, identity_source="claimed"
    )
    browser.cookies.set("anon", token)
    steam_sign_in(browser, next(STEAM_IDS))
    assert browser.get(ME).json()["user"]["display_name"] == account.DEFAULT_DISPLAY_NAME


def test_a_name_already_set_is_kept(browser: TestClient, conn: Connection, make: Factory) -> None:
    user = make.user("Chosen earlier")
    steam_id = next(STEAM_IDS)
    make.linked_account(user, "steam", steam_id)
    match = make.match()
    player = make.player(match, platform="steam", platform_id=steam_id)
    set_player_name(conn, player, "From a replay")
    make.user_match(match, user_id=user)
    steam_sign_in(browser, steam_id)
    assert browser.get(ME).json()["user"]["display_name"] == "Chosen earlier"
