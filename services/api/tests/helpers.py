"""What several test files need to act out a sign-in. Everything here is made up."""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from typing import Any

import httpx2
from fastapi.testclient import TestClient

from ma_api import sessions
from ma_api.app import create_app
from ma_api.errors import ApiError
from ma_api.settings import PREFIX, Settings
from ma_api.steam import OPENID_NS
from ma_api.storage import ObjectStore
from ma_db.testing import Connection

STEAM_START = f"{PREFIX}/auth/steam"
STEAM_CALLBACK = f"{PREFIX}/auth/steam/callback"
EPIC_START = f"{PREFIX}/auth/epic"
EPIC_CALLBACK = f"{PREFIX}/auth/epic/callback"
ME = f"{PREFIX}/me"
SIGNED = "signed,op_endpoint,claimed_id,identity,return_to,response_nonce,assoc_handle"
# One per test that needs an account of its own, apart from the ids other test files write out.
STEAM_IDS = iter(f"7656119{number:010d}" for number in range(5_000_000_000, 5_000_001_000))
EPIC_IDS = iter(f"{number:032x}" for number in range(1, 1000))


class FakeProviders:
    """Steam's and Epic's servers, as the API sees them."""

    def __init__(self) -> None:
        self.steam_reply = f"ns:{OPENID_NS}\nis_valid:true\n"
        self.steam_calls = 0
        self.token_status = 200
        self.token_body: Any = {"access_token": "epic-token", "account_id": "0" * 32}
        self.userinfo_status = 200
        self.userinfo_body: Any = {"sub": "0" * 32, "preferred_username": "Epic name"}
        self.epic_requests: list[httpx2.Request] = []

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        if request.url.host == "steamcommunity.com":
            self.steam_calls += 1
            return httpx2.Response(200, text=self.steam_reply)
        self.epic_requests.append(request)
        if request.url.path.endswith("/token"):
            return httpx2.Response(self.token_status, json=self.token_body)
        return httpx2.Response(self.userinfo_status, json=self.userinfo_body)

    def epic_account(self, account_id: str, name: str = "Epic name") -> None:
        self.token_body = {"access_token": "epic-token", "account_id": account_id}
        self.userinfo_body = {"sub": account_id, "preferred_username": name}


class FakeStore:
    """The object store, as the API sees it."""

    def __init__(self) -> None:
        self.sizes: dict[str, int] = {}
        self.down = False

    def presign_put(self, key: str, size: int) -> str:
        return f"https://store.test/{key}?size={size}"

    def object_size(self, key: str) -> int | None:
        if self.down:
            raise ApiError(503, "unavailable")
        return self.sizes.get(key)


@contextmanager
def browser_for(
    settings: Settings, providers: FakeProviders, store: ObjectStore | None = None
) -> Iterator[TestClient]:
    app = create_app(settings, http_transport=httpx2.MockTransport(providers.handle), storage=store)
    with TestClient(
        app,
        base_url=settings.site_url,
        headers={"Origin": settings.site_origin},
        follow_redirects=False,
    ) as client:
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


def steam_sign_in(browser: TestClient, steam_id: str, return_to: str = "/mine") -> httpx2.Response:
    start = browser.get(STEAM_START, params={"return_to": return_to})
    assert start.status_code == 303
    return browser.get(STEAM_CALLBACK, params=steam_answer(start, steam_id))


def epic_sign_in(browser: TestClient, return_to: str = "/mine") -> httpx2.Response:
    start = browser.get(EPIC_START, params={"return_to": return_to})
    assert start.status_code == 303
    state = httpx2.URL(start.headers["location"]).params["state"]
    return browser.get(EPIC_CALLBACK, params={"state": state, "code": "the-code"})


def assert_failed(response: httpx2.Response, site: str, code: str = "auth_failed") -> None:
    assert response.status_code == 303
    assert response.headers["location"] == f"{site}/?auth_error={code}"
    assert not any(c.startswith("session=") for c in response.headers.get_list("set-cookie"))


def anonymous_session(conn: Connection, *, valid: bool = True) -> tuple[uuid.UUID, str]:
    token = sessions.new_token()
    row = conn.execute(
        "INSERT INTO anonymous_sessions (token_hash, expires_at) VALUES (%s, now() + %s) "
        "RETURNING id",
        (sessions.token_hash(token), timedelta(days=1 if valid else -1)),
    ).fetchone()
    assert row is not None
    return row[0], token


def user_session(conn: Connection, user: uuid.UUID, *, valid: bool = True) -> str:
    token = sessions.new_token()
    conn.execute(
        "INSERT INTO auth_sessions (token_hash, user_id, expires_at) VALUES (%s, %s, now() + %s)",
        (sessions.token_hash(token), user, timedelta(days=1 if valid else -1)),
    )
    return token
