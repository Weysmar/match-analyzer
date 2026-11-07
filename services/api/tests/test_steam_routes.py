"""The whole sign-in, with a simulated Steam, against PostgreSQL with the API's own role."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta

import httpx2
import psycopg
import pytest
from fastapi.testclient import TestClient

from ma_api import account, sessions
from ma_api.app import create_app
from ma_api.settings import PREFIX, Settings
from ma_api.steam import OPENID_NS
from ma_db.testing import Connection, Factory, count

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_limits")]

SITE = "http://testserver"
START = f"{PREFIX}/auth/steam"
CALLBACK = f"{PREFIX}/auth/steam/callback"
ME = f"{PREFIX}/me"
SIGNED = "signed,op_endpoint,claimed_id,identity,return_to,response_nonce,assoc_handle"
# Made-up ids, one per test that needs an account of its own, apart from the other test files.
IDS = iter(f"7656119{number:010d}" for number in range(5_000_000_000, 5_000_001_000))


class FakeSteam:
    def __init__(self) -> None:
        self.reply = f"ns:{OPENID_NS}\nis_valid:true\n"
        self.calls = 0

    def handle(self, _: httpx2.Request) -> httpx2.Response:
        self.calls += 1
        return httpx2.Response(200, text=self.reply)


@pytest.fixture
def steam() -> FakeSteam:
    return FakeSteam()


@contextmanager
def browser_for(settings: Settings, steam: FakeSteam) -> Iterator[TestClient]:
    app = create_app(settings, http_transport=httpx2.MockTransport(steam.handle))
    with TestClient(
        app,
        base_url=settings.site_url,
        headers={"Origin": settings.site_origin},
        follow_redirects=False,
    ) as client:
        yield client


@pytest.fixture
def browser(settings: Settings, steam: FakeSteam) -> Iterator[TestClient]:
    with browser_for(settings, steam) as client:
        yield client


def steam_answer(start: httpx2.Response, steam_id: str) -> dict[str, str]:
    """What Steam adds to the URL it sends the browser back to."""
    return_to = httpx2.URL(start.headers["location"]).params["openid.return_to"]
    identity = f"https://steamcommunity.com/openid/id/{steam_id}"
    return {
        "state": httpx2.URL(return_to).params["state"],
        "openid.ns": OPENID_NS,
        "openid.mode": "id_res",
        "openid.op_endpoint": "https://steamcommunity.com/openid/login",
        "openid.claimed_id": identity,
        "openid.identity": identity,
        "openid.return_to": return_to,
        "openid.response_nonce": "2026-11-07T00:00:00Zabc",
        "openid.assoc_handle": "1234567890",
        "openid.signed": SIGNED,
        "openid.sig": "c2lnbmF0dXJl",
    }


def sign_in(browser: TestClient, steam_id: str, return_to: str = "/mine") -> httpx2.Response:
    start = browser.get(START, params={"return_to": return_to})
    assert start.status_code == 303
    return browser.get(CALLBACK, params=steam_answer(start, steam_id))


def users_of(conn: Connection, steam_id: str) -> int:
    return count(
        conn,
        "SELECT count(*) FROM linked_accounts "
        "WHERE provider = 'steam' AND provider_account_id = %s",
        steam_id,
    )


def assert_failed(response: httpx2.Response, code: str = "auth_failed") -> None:
    assert response.status_code == 303
    assert response.headers["location"] == f"{SITE}/?auth_error={code}"
    assert "session=" not in response.headers.get("set-cookie", "")


def test_start_sends_the_browser_to_steam(browser: TestClient) -> None:
    response = browser.get(START, params={"return_to": "/mine"})
    assert response.status_code == 303
    url = httpx2.URL(response.headers["location"])
    assert url.host == "steamcommunity.com"
    assert url.params["openid.realm"] == SITE
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("steam_flow=")
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Max-Age=600" in cookie
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("return_to", ["https://evil.test/", "//evil.test", "mine"])
def test_start_refuses_a_redirect_elsewhere(browser: TestClient, return_to: str) -> None:
    response = browser.get(START, params={"return_to": return_to})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"
    assert return_to not in response.text
    assert "set-cookie" not in response.headers


def test_a_first_sign_in_creates_the_account(
    browser: TestClient, conn: Connection, steam: FakeSteam
) -> None:
    steam_id = next(IDS)
    response = sign_in(browser, steam_id)
    assert response.status_code == 303
    assert response.headers["location"] == f"{SITE}/mine"
    assert steam.calls == 1
    cookies = response.headers.get_list("set-cookie")
    session = next(cookie for cookie in cookies if cookie.startswith("session="))
    assert "HttpOnly" in session
    assert "SameSite=lax" in session
    assert "Max-Age=2592000" in session
    # The flow is over.
    assert any(cookie.startswith('steam_flow=""') for cookie in cookies)

    me = browser.get(ME)
    body = me.json()
    assert body["kind"] == "user"
    assert body["user"]["display_name"] == account.DEFAULT_DISPLAY_NAME
    assert body["linked_accounts"] == [{"provider": "steam", "display_name": None}]
    assert steam_id not in me.text
    assert users_of(conn, steam_id) == 1


def test_the_session_is_stored_hashed_and_expires(browser: TestClient, conn: Connection) -> None:
    sign_in(browser, next(IDS))
    token = browser.cookies["session"]
    row = conn.execute(
        "SELECT expires_at - now() FROM auth_sessions WHERE token_hash = %s",
        (sessions.token_hash(token),),
    ).fetchone()
    assert row is not None
    assert timedelta(days=29) < row[0] <= timedelta(days=30)
    assert (
        count(conn, "SELECT count(*) FROM auth_sessions WHERE token_hash = %s", token.encode()) == 0
    )


def test_coming_back_finds_the_same_account(
    settings: Settings, steam: FakeSteam, conn: Connection
) -> None:
    steam_id = next(IDS)
    identities = []
    for _ in range(2):
        with browser_for(settings, steam) as browser:
            sign_in(browser, steam_id)
            identities.append(browser.get(ME).json()["user"]["id"])
    assert identities[0] == identities[1]
    assert users_of(conn, steam_id) == 1


def test_a_stranger_cannot_sign_someone_in_with_a_ready_made_link(
    browser: TestClient, settings: Settings, steam: FakeSteam, conn: Connection
) -> None:
    """The attacker's own valid answer, opened by a victim who never started a sign-in."""
    steam_id = next(IDS)
    answer = steam_answer(browser.get(START), steam_id)
    with browser_for(settings, steam) as victim:
        response = victim.get(CALLBACK, params=answer)
        assert_failed(response)
        assert victim.get(ME).json()["kind"] == "none"
    assert steam.calls == 0
    assert users_of(conn, steam_id) == 0


def test_an_answer_for_another_browsers_flow_is_refused(
    browser: TestClient, settings: Settings, steam: FakeSteam
) -> None:
    answer = steam_answer(browser.get(START), next(IDS))
    with browser_for(settings, steam) as victim:
        victim.get(START)
        assert_failed(victim.get(CALLBACK, params=answer))
    assert steam.calls == 0


def test_a_flow_serves_once(browser: TestClient, steam: FakeSteam) -> None:
    start = browser.get(START)
    answer = steam_answer(start, next(IDS))
    browser.get(CALLBACK, params=answer)
    assert browser.post(f"{PREFIX}/auth/logout").status_code == 204
    assert_failed(browser.get(CALLBACK, params=answer))
    assert steam.calls == 1


def test_an_altered_flow_cookie_is_refused(browser: TestClient, steam: FakeSteam) -> None:
    answer = steam_answer(browser.get(START), next(IDS))
    altered = browser.cookies["steam_flow"] + "0"
    browser.cookies.clear()
    browser.cookies.set("steam_flow", altered)
    assert_failed(browser.get(CALLBACK, params=answer))
    assert steam.calls == 0


def test_when_steam_does_not_confirm_nothing_is_created(
    browser: TestClient, conn: Connection, steam: FakeSteam
) -> None:
    steam.reply = f"ns:{OPENID_NS}\nis_valid:false\n"
    steam_id = next(IDS)
    assert_failed(sign_in(browser, steam_id))
    assert steam.calls == 1
    assert users_of(conn, steam_id) == 0
    assert browser.get(ME).json()["kind"] == "none"


def test_a_failure_ends_the_flow_too(browser: TestClient, steam: FakeSteam) -> None:
    steam.reply = "is_valid:false\n"
    response = sign_in(browser, next(IDS))
    assert response.headers["set-cookie"].startswith('steam_flow=""')


def test_signing_in_while_signed_in_links_the_account(
    browser: TestClient, conn: Connection, make: Factory
) -> None:
    user = make.user()
    make.linked_account(user, "epic", "epic-account-1")
    token = sessions.new_token()
    conn.execute(
        "INSERT INTO auth_sessions (token_hash, user_id, expires_at) VALUES (%s, %s, now() + %s)",
        (sessions.token_hash(token), user, timedelta(days=1)),
    )
    browser.cookies.set("session", token)
    steam_id = next(IDS)
    response = sign_in(browser, steam_id)
    assert response.headers["location"] == f"{SITE}/mine"
    # The session goes on.
    assert not any(c.startswith("session=") for c in response.headers.get_list("set-cookie"))
    body = browser.get(ME).json()
    assert body["user"]["id"] == str(user)
    assert {account["provider"] for account in body["linked_accounts"]} == {"steam", "epic"}


def test_someone_elses_account_is_not_linked(
    browser: TestClient, settings: Settings, steam: FakeSteam
) -> None:
    taken = next(IDS)
    with browser_for(settings, steam) as other:
        sign_in(other, taken)
        theirs = other.get(ME).json()["user"]["id"]
    sign_in(browser, next(IDS))
    mine = browser.get(ME).json()["user"]["id"]
    assert_failed(sign_in(browser, taken), "account_already_linked")
    # Nobody moved: no merge in V1.
    assert browser.get(ME).json()["user"]["id"] == mine
    assert mine != theirs


def test_a_second_account_of_the_same_provider_is_not_linked(browser: TestClient) -> None:
    sign_in(browser, next(IDS))
    assert_failed(sign_in(browser, next(IDS)), "account_already_linked")
    assert len(browser.get(ME).json()["linked_accounts"]) == 1


def test_signing_in_again_with_ones_own_account_changes_nothing(browser: TestClient) -> None:
    steam_id = next(IDS)
    sign_in(browser, steam_id)
    token = browser.cookies["session"]
    response = sign_in(browser, steam_id)
    assert response.headers["location"] == f"{SITE}/mine"
    assert browser.cookies["session"] == token


def test_https_cookies_are_bound_to_the_host(api_url: str, steam: FakeSteam) -> None:
    site = "https://example.test"
    settings = Settings(database_url=api_url, site_url=site, session_secret="s")
    with browser_for(settings, steam) as browser:
        start = browser.get(START)
        assert start.headers["set-cookie"].startswith("__Host-steam_flow=")
        assert "Secure" in start.headers["set-cookie"]
        response = browser.get(CALLBACK, params=steam_answer(start, next(IDS)))
        session = next(
            cookie
            for cookie in response.headers.get_list("set-cookie")
            if cookie.startswith("__Host-session=")
        )
        assert "Secure" in session
        assert "Path=/" in session
        assert browser.get(ME).json()["kind"] == "user"


@pytest.mark.parametrize("route", [START, CALLBACK])
def test_sign_in_routes_are_rate_limited(api_url: str, steam: FakeSteam, route: str) -> None:
    settings = Settings(
        database_url=api_url, site_url=SITE, session_secret="s", rate_auth_ip_per_minute=1
    )
    with browser_for(settings, steam) as browser:
        browser.get(route)
        refused = browser.get(route)
    assert refused.status_code == 429
    assert refused.json()["error"]["code"] == "rate_limited"


def test_failed_callbacks_use_up_the_limit(api_url: str, steam: FakeSteam) -> None:
    settings = Settings(
        database_url=api_url, site_url=SITE, session_secret="s", rate_auth_ip_per_minute=2
    )
    with browser_for(settings, steam) as browser:
        assert_failed(browser.get(CALLBACK))
        assert_failed(browser.get(CALLBACK))
        assert browser.get(CALLBACK).status_code == 429


def test_logout_ends_the_session(browser: TestClient, conn: Connection) -> None:
    sign_in(browser, next(IDS))
    token = browser.cookies["session"]
    response = browser.post(f"{PREFIX}/auth/logout")
    assert response.status_code == 204
    assert response.headers["set-cookie"].startswith('session=""')
    assert browser.get(ME).json()["kind"] == "none"
    # The row is gone: the old cookie, if someone kept it, leads nowhere.
    browser.cookies.set("session", token)
    assert browser.get(ME).json()["kind"] == "none"
    assert (
        count(
            conn,
            "SELECT count(*) FROM auth_sessions WHERE token_hash = %s",
            sessions.token_hash(token),
        )
        == 0
    )


def test_logout_keeps_the_account(browser: TestClient, conn: Connection) -> None:
    steam_id = next(IDS)
    sign_in(browser, steam_id)
    browser.post(f"{PREFIX}/auth/logout")
    assert users_of(conn, steam_id) == 1


def test_logout_without_a_session_is_fine(browser: TestClient) -> None:
    assert browser.post(f"{PREFIX}/auth/logout").status_code == 204
    browser.cookies.set("session", "forged")
    assert browser.post(f"{PREFIX}/auth/logout").status_code == 204


def test_logout_from_another_site_is_refused(browser: TestClient) -> None:
    sign_in(browser, next(IDS))
    response = browser.post(f"{PREFIX}/auth/logout", headers={"Origin": "https://evil.test"})
    assert response.status_code == 403
    assert browser.get(ME).json()["kind"] == "user"


def test_losing_the_race_for_a_first_sign_in_leaves_nothing_behind(
    api_url: str, conn: Connection, make: Factory
) -> None:
    """Two first sign-ins at once: the loser finds the winner's user, and leaves no empty one."""
    steam_id = next(IDS)
    winner = make.user()
    make.linked_account(winner, "steam", steam_id)
    before = count(conn, "SELECT count(*) FROM users")
    with psycopg.connect(api_url) as api:
        assert account._create(api, "steam", steam_id, None) == winner
    assert count(conn, "SELECT count(*) FROM users") == before
