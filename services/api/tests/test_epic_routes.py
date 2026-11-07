"""The whole sign-in, with a simulated Epic, against PostgreSQL with the API's own role."""

from collections.abc import Iterator
from dataclasses import replace

import httpx2
import pytest
from fastapi.testclient import TestClient

from ma_api import account
from ma_api.settings import PREFIX, Settings
from ma_db.testing import Connection, count

from .helpers import (
    EPIC_CALLBACK,
    EPIC_IDS,
    EPIC_START,
    ME,
    STEAM_IDS,
    FakeProviders,
    assert_failed,
    browser_for,
    epic_sign_in,
    steam_sign_in,
)

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_limits")]

SITE = "http://testserver"


@pytest.fixture
def epic_settings(settings: Settings) -> Settings:
    return replace(
        settings,
        epic_login=True,
        epic_client_id="the-client",
        epic_client_secret="the-secret",
        epic_redirect_uri=f"{SITE}{EPIC_CALLBACK}",
    )


@pytest.fixture
def epic_browser(epic_settings: Settings, providers: FakeProviders) -> Iterator[TestClient]:
    with browser_for(epic_settings, providers) as client:
        yield client


def accounts_of(conn: Connection, account_id: str) -> int:
    return count(
        conn,
        "SELECT count(*) FROM linked_accounts WHERE provider = 'epic' AND provider_account_id = %s",
        account_id,
    )


def test_me_tells_the_site_the_flag_is_on(epic_browser: TestClient) -> None:
    assert epic_browser.get(ME).json()["features"]["epic_login"] is True


def test_a_first_sign_in_creates_the_account(
    epic_browser: TestClient, providers: FakeProviders, conn: Connection
) -> None:
    account_id = next(EPIC_IDS)
    providers.epic_account(account_id, "A chosen name")
    response = epic_sign_in(epic_browser)
    assert response.status_code == 303
    assert response.headers["location"] == f"{SITE}/mine"
    me = epic_browser.get(ME)
    body = me.json()
    assert body["kind"] == "user"
    assert body["user"]["display_name"] == "A chosen name"
    assert body["linked_accounts"] == [{"provider": "epic", "display_name": "A chosen name"}]
    assert account_id not in me.text
    assert accounts_of(conn, account_id) == 1


def test_no_name_from_epic_still_signs_in(
    epic_browser: TestClient, providers: FakeProviders
) -> None:
    providers.epic_account(next(EPIC_IDS))
    providers.userinfo_status = 500
    epic_sign_in(epic_browser)
    body = epic_browser.get(ME).json()
    assert body["kind"] == "user"
    assert body["user"]["display_name"] == account.DEFAULT_DISPLAY_NAME


def test_coming_back_finds_the_same_account(
    epic_settings: Settings, providers: FakeProviders
) -> None:
    providers.epic_account(next(EPIC_IDS))
    identities = []
    for _ in range(2):
        with browser_for(epic_settings, providers) as browser:
            epic_sign_in(browser)
            identities.append(browser.get(ME).json()["user"]["id"])
    assert identities[0] == identities[1]


def test_a_stranger_cannot_sign_someone_in_with_a_ready_made_link(
    epic_browser: TestClient, epic_settings: Settings, providers: FakeProviders
) -> None:
    start = epic_browser.get(EPIC_START)
    state = httpx2.URL(start.headers["location"]).params["state"]
    with browser_for(epic_settings, providers) as victim:
        response = victim.get(EPIC_CALLBACK, params={"state": state, "code": "the-attackers"})
        assert_failed(response, SITE)
        assert victim.get(ME).json()["kind"] == "none"
    assert providers.epic_requests == []


def test_a_wrong_state_is_refused(epic_browser: TestClient, providers: FakeProviders) -> None:
    epic_browser.get(EPIC_START)
    response = epic_browser.get(EPIC_CALLBACK, params={"state": "wrong", "code": "x"})
    assert_failed(response, SITE)
    assert providers.epic_requests == []


def test_a_flow_serves_once(epic_browser: TestClient, providers: FakeProviders) -> None:
    providers.epic_account(next(EPIC_IDS))
    start = epic_browser.get(EPIC_START)
    params = {"state": httpx2.URL(start.headers["location"]).params["state"], "code": "x"}
    epic_browser.get(EPIC_CALLBACK, params=params)
    assert epic_browser.post(f"{PREFIX}/auth/logout").status_code == 204
    before = len(providers.epic_requests)
    assert_failed(epic_browser.get(EPIC_CALLBACK, params=params), SITE)
    assert len(providers.epic_requests) == before


def test_a_refused_code_creates_nothing(
    epic_browser: TestClient, providers: FakeProviders, conn: Connection
) -> None:
    account_id = next(EPIC_IDS)
    providers.epic_account(account_id)
    providers.token_status = 400
    assert_failed(epic_sign_in(epic_browser), SITE)
    assert accounts_of(conn, account_id) == 0
    assert epic_browser.get(ME).json()["kind"] == "none"


def test_a_steam_user_links_epic(epic_browser: TestClient, providers: FakeProviders) -> None:
    providers.epic_account(next(EPIC_IDS))
    steam_sign_in(epic_browser, next(STEAM_IDS))
    before = epic_browser.get(ME).json()["user"]["id"]
    response = epic_sign_in(epic_browser)
    assert response.headers["location"] == f"{SITE}/mine"
    body = epic_browser.get(ME).json()
    assert body["user"]["id"] == before
    assert {link["provider"] for link in body["linked_accounts"]} == {"steam", "epic"}


def test_someone_elses_epic_account_is_not_linked(
    epic_browser: TestClient, epic_settings: Settings, providers: FakeProviders
) -> None:
    providers.epic_account(next(EPIC_IDS))
    with browser_for(epic_settings, providers) as other:
        epic_sign_in(other)
    steam_sign_in(epic_browser, next(STEAM_IDS))
    assert_failed(epic_sign_in(epic_browser), SITE, "account_already_linked")
    assert len(epic_browser.get(ME).json()["linked_accounts"]) == 1


def test_the_sign_in_is_rate_limited(epic_settings: Settings, providers: FakeProviders) -> None:
    limited = replace(epic_settings, rate_auth_ip_per_minute=2)
    with browser_for(limited, providers) as browser:
        assert_failed(browser.get(EPIC_CALLBACK), SITE)
        assert browser.get(EPIC_START).status_code == 303
        assert browser.get(EPIC_START).status_code == 429
