"""The right to erasure, through the API. What the worker's cleanup does comes at step 9."""

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ma_api.settings import PREFIX, Settings
from ma_db.testing import Connection, Factory, count

from .helpers import ME, STEAM_IDS, FakeProviders, anonymous_session, browser_for, steam_sign_in

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_limits")]

ERASE = f"{PREFIX}/me"
ERASE_ANONYMOUS = f"{PREFIX}/me/anonymous"


def cleanup_jobs(conn: Connection, match: uuid.UUID) -> list[tuple[Any, ...]]:
    return conn.execute(
        "SELECT status FROM jobs WHERE kind = 'gc_match' AND payload->>'match_id' = %s",
        (str(match),),
    ).fetchall()


def sign_in(browser: TestClient) -> tuple[uuid.UUID, str]:
    steam_id = next(STEAM_IDS)
    steam_sign_in(browser, steam_id)
    return uuid.UUID(browser.get(ME).json()["user"]["id"]), steam_id


def test_erasing_an_account_removes_everything_of_mine(
    browser: TestClient, conn: Connection, make: Factory
) -> None:
    user, steam_id = sign_in(browser)
    match = make.match()
    make.user_match(match, user_id=user)
    make.upload(user_id=user, match_id=match)
    conn.execute(
        "INSERT INTO player_claims (user_id, platform, platform_id) VALUES (%s, 'psn', 'x')",
        (user,),
    )
    token = browser.cookies["session"]

    response = browser.delete(ERASE)
    assert response.status_code == 202
    assert response.content == b""
    for query in (
        "SELECT count(*) FROM users WHERE id = %s",
        "SELECT count(*) FROM linked_accounts WHERE user_id = %s",
        "SELECT count(*) FROM auth_sessions WHERE user_id = %s",
        "SELECT count(*) FROM user_matches WHERE user_id = %s",
        "SELECT count(*) FROM uploads WHERE user_id = %s",
        "SELECT count(*) FROM player_claims WHERE user_id = %s",
    ):
        assert count(conn, query, user) == 0, query
    assert (
        count(conn, "SELECT count(*) FROM linked_accounts WHERE provider_account_id = %s", steam_id)
        == 0
    )
    # The session is gone, and an old copy of the cookie leads nowhere.
    assert any(c.startswith('session=""') for c in response.headers.get_list("set-cookie"))
    browser.cookies.set("session", token)
    assert browser.get(ME).json()["kind"] == "none"


def test_a_cleanup_job_is_queued_per_match(
    browser: TestClient, conn: Connection, make: Factory
) -> None:
    user, _ = sign_in(browser)
    matches = [make.match(), make.match()]
    for match in matches:
        make.user_match(match, user_id=user)
    browser.delete(ERASE)
    for match in matches:
        assert cleanup_jobs(conn, match) == [("queued",)]


def test_a_match_someone_else_owns_stays_theirs(
    browser: TestClient, conn: Connection, make: Factory
) -> None:
    """Deleting it, if it has no owner left, is the cleanup job's call."""
    user, _ = sign_in(browser)
    other = make.user()
    match = make.match()
    make.user_match(match, user_id=user)
    theirs = make.user_match(match, user_id=other)
    browser.delete(ERASE)
    assert count(conn, "SELECT count(*) FROM matches WHERE id = %s", match) == 1
    assert count(conn, "SELECT count(*) FROM user_matches WHERE id = %s", theirs) == 1


def test_this_browsers_anonymous_session_goes_too(
    browser: TestClient, conn: Connection, make: Factory
) -> None:
    user, _ = sign_in(browser)
    session, token = anonymous_session(conn)
    match = make.match()
    make.user_match(match, anonymous_session_id=session)
    browser.cookies.set("anon", token)
    response = browser.delete(ERASE)
    assert response.status_code == 202
    assert count(conn, "SELECT count(*) FROM anonymous_sessions WHERE id = %s", session) == 0
    assert cleanup_jobs(conn, match) == [("queued",)]
    assert any(c.startswith('anon=""') for c in response.headers.get_list("set-cookie"))
    assert count(conn, "SELECT count(*) FROM users WHERE id = %s", user) == 0


def test_a_later_sign_in_starts_over(
    browser: TestClient, settings: Settings, providers: FakeProviders
) -> None:
    user, steam_id = sign_in(browser)
    browser.delete(ERASE)
    with browser_for(settings, providers) as later:
        steam_sign_in(later, steam_id)
        assert later.get(ME).json()["user"]["id"] != str(user)


@pytest.mark.parametrize("cookie", [None, "forged"])
def test_erasing_needs_an_account(browser: TestClient, cookie: str | None) -> None:
    if cookie is not None:
        browser.cookies.set("session", cookie)
    response = browser.delete(ERASE)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_signed_in"


def test_an_anonymous_visitor_has_no_account_to_erase(
    browser: TestClient, conn: Connection, make: Factory
) -> None:
    session, token = anonymous_session(conn)
    browser.cookies.set("anon", token)
    assert browser.delete(ERASE).status_code == 401
    assert count(conn, "SELECT count(*) FROM anonymous_sessions WHERE id = %s", session) == 1


def test_another_site_cannot_erase_an_account(browser: TestClient, conn: Connection) -> None:
    user, _ = sign_in(browser)
    response = browser.delete(ERASE, headers={"Origin": "https://evil.test"})
    assert response.status_code == 403
    assert count(conn, "SELECT count(*) FROM users WHERE id = %s", user) == 1


def test_erasing_an_anonymous_session(browser: TestClient, conn: Connection, make: Factory) -> None:
    session, token = anonymous_session(conn)
    match = make.match()
    make.user_match(match, anonymous_session_id=session)
    upload = make.upload(anonymous_session_id=session, match_id=match)
    conn.execute(
        "INSERT INTO player_claims (anonymous_session_id, platform, platform_id) "
        "VALUES (%s, 'psn', 'x')",
        (session,),
    )
    browser.cookies.set("anon", token)
    response = browser.delete(ERASE_ANONYMOUS)
    assert response.status_code == 202
    assert any(c.startswith('anon=""') for c in response.headers.get_list("set-cookie"))
    assert count(conn, "SELECT count(*) FROM anonymous_sessions WHERE id = %s", session) == 0
    assert count(conn, "SELECT count(*) FROM user_matches WHERE match_id = %s", match) == 0
    assert count(conn, "SELECT count(*) FROM uploads WHERE id = %s", upload) == 0
    assert (
        count(conn, "SELECT count(*) FROM player_claims WHERE anonymous_session_id = %s", session)
        == 0
    )
    assert cleanup_jobs(conn, match) == [("queued",)]
    assert browser.get(ME).json()["kind"] == "none"


def test_erasing_without_a_session_is_fine(browser: TestClient) -> None:
    assert browser.delete(ERASE_ANONYMOUS).status_code == 202
    browser.cookies.set("anon", "forged")
    assert browser.delete(ERASE_ANONYMOUS).status_code == 202


def test_it_only_erases_this_session(browser: TestClient, conn: Connection, make: Factory) -> None:
    _, token = anonymous_session(conn)
    other, _ = anonymous_session(conn)
    match = make.match()
    link = make.user_match(match, anonymous_session_id=other)
    browser.cookies.set("anon", token)
    browser.delete(ERASE_ANONYMOUS)
    assert count(conn, "SELECT count(*) FROM user_matches WHERE id = %s", link) == 1
    assert cleanup_jobs(conn, match) == []


def test_a_signed_in_user_keeps_their_account(
    browser: TestClient, conn: Connection, make: Factory
) -> None:
    user, _ = sign_in(browser)
    session, token = anonymous_session(conn)
    browser.cookies.set("anon", token)
    browser.delete(ERASE_ANONYMOUS)
    assert count(conn, "SELECT count(*) FROM anonymous_sessions WHERE id = %s", session) == 0
    assert count(conn, "SELECT count(*) FROM users WHERE id = %s", user) == 1
    assert browser.get(ME).json()["kind"] == "user"


def test_another_site_cannot_erase_a_session(browser: TestClient, conn: Connection) -> None:
    session, token = anonymous_session(conn)
    browser.cookies.set("anon", token)
    response = browser.delete(ERASE_ANONYMOUS, headers={"Origin": "https://evil.test"})
    assert response.status_code == 403
    assert count(conn, "SELECT count(*) FROM anonymous_sessions WHERE id = %s", session) == 1
