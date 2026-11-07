"""Epic's flag, forged callbacks and Epic's answers. No database needed."""

import base64
import logging

import httpx2
import pytest
from fastapi.testclient import TestClient

from ma_api.app import create_app
from ma_api.epic import login_url, verified_account
from ma_api.settings import PREFIX, Settings, SettingsError

SITE = "https://example.test"
REDIRECT = f"{SITE}{PREFIX}/auth/epic/callback"
SECRET = "the-client-secret"
SETTINGS = Settings(
    database_url="unused",
    site_url=SITE,
    epic_login=True,
    epic_client_id="the-client",
    epic_client_secret=SECRET,
    epic_redirect_uri=REDIRECT,
)
NONCE = "the-nonce"
ACCOUNT = "0123456789abcdef0123456789abcdef"
QUERY = [("state", NONCE), ("code", "the-code")]


class Epic:
    def __init__(self) -> None:
        self.token_status = 200
        self.token_body: object = {"access_token": "the-token", "account_id": ACCOUNT}
        self.info_status = 200
        self.info_body: object = {"sub": ACCOUNT, "preferred_username": "A name"}
        self.requests: list[httpx2.Request] = []

    def client(self) -> httpx2.Client:
        return httpx2.Client(transport=httpx2.MockTransport(self._handle))

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if str(request.url) == SETTINGS.epic_token_url:
            return httpx2.Response(self.token_status, json=self.token_body)
        return httpx2.Response(self.info_status, json=self.info_body)

    def verify(self, query: list[tuple[str, str]] = QUERY) -> tuple[str, str | None] | None:
        return verified_account(self.client(), SETTINGS, query, NONCE)


def test_a_good_callback_gives_the_account_and_its_name() -> None:
    assert Epic().verify() == (ACCOUNT, "A name")


def test_what_epic_is_asked() -> None:
    epic = Epic()
    epic.verify()
    token, info = epic.requests
    assert token.method == "POST"
    credentials = base64.b64decode(token.headers["authorization"].removeprefix("Basic "))
    assert credentials.decode() == f"the-client:{SECRET}"
    body = httpx2.QueryParams(token.content.decode())
    assert body["grant_type"] == "authorization_code"
    assert body["code"] == "the-code"
    assert body["redirect_uri"] == REDIRECT
    assert SECRET not in token.content.decode()
    assert str(info.url) == SETTINGS.epic_userinfo_url
    assert info.headers["authorization"] == "Bearer the-token"


@pytest.mark.parametrize(
    "query",
    [
        pytest.param([("code", "the-code")], id="no-state"),
        pytest.param([("state", "other"), ("code", "the-code")], id="another-browser"),
        pytest.param([("state", "é"), ("code", "the-code")], id="odd-state"),
        pytest.param([("state", NONCE)], id="no-code"),
        pytest.param([("state", NONCE), ("code", "")], id="empty-code"),
        pytest.param([("state", NONCE), ("code", "x" * 2049)], id="huge-code"),
        pytest.param([("state", NONCE), ("error", "access_denied")], id="denied"),
        pytest.param(
            [("state", NONCE), ("code", "x"), ("error", "access_denied")], id="denied-with-code"
        ),
        pytest.param([*QUERY, ("code", "another")], id="repeated-code"),
        pytest.param([*QUERY, ("state", NONCE)], id="repeated-state"),
    ],
)
def test_a_forged_callback_never_reaches_epic(query: list[tuple[str, str]]) -> None:
    epic = Epic()
    assert epic.verify(query) is None
    assert epic.requests == []


@pytest.mark.parametrize(
    "body",
    [
        {},
        [],
        "text",
        {"access_token": "the-token"},
        {"account_id": ACCOUNT},
        {"access_token": "", "account_id": ACCOUNT},
        {"access_token": 1, "account_id": ACCOUNT},
        {"access_token": "the-token", "account_id": ""},
        {"access_token": "the-token", "account_id": 12},
        {"access_token": "the-token", "account_id": "../other"},
        {"access_token": "the-token", "account_id": "x" * 65},
    ],
)
def test_a_token_answer_without_an_account_refuses(body: object) -> None:
    epic = Epic()
    epic.token_body = body
    assert epic.verify() is None
    # Without a token, there is nothing to ask for a name with.
    assert len(epic.requests) == 1


def test_a_refused_code_refuses() -> None:
    epic = Epic()
    epic.token_status = 400
    assert epic.verify() is None


def test_epic_out_of_reach_refuses() -> None:
    def fail(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("unreachable", request=request)

    client = httpx2.Client(transport=httpx2.MockTransport(fail))
    assert verified_account(client, SETTINGS, QUERY, NONCE) is None


def test_a_token_answer_that_is_not_json_refuses() -> None:
    def text(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, text="<html>")

    client = httpx2.Client(transport=httpx2.MockTransport(text))
    assert verified_account(client, SETTINGS, QUERY, NONCE) is None


@pytest.mark.parametrize(
    "body",
    [
        {},
        [],
        {"sub": ACCOUNT},
        {"sub": ACCOUNT, "preferred_username": ""},
        {"sub": ACCOUNT, "preferred_username": 1},
        {"sub": ACCOUNT, "preferred_username": "x" * 65},
        {"sub": "someone-else", "preferred_username": "Not them"},
        {"preferred_username": "Not said whose"},
    ],
)
def test_a_useless_name_does_not_stop_the_sign_in(body: object) -> None:
    epic = Epic()
    epic.info_body = body
    assert epic.verify() == (ACCOUNT, None)


def test_a_failing_userinfo_does_not_stop_the_sign_in() -> None:
    epic = Epic()
    epic.info_status = 500
    assert epic.verify() == (ACCOUNT, None)


def test_the_log_never_holds_a_secret_or_an_identity(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="ma_api"):
        epic = Epic()
        epic.verify()
        epic.token_status = 400
        epic.verify()
        epic.verify([("state", "other"), ("code", "the-code")])
    assert "refused" in caplog.text
    for secret in (SECRET, "the-token", "the-code", ACCOUNT, "A name"):
        assert secret not in caplog.text


def test_the_login_url_holds_no_secret() -> None:
    url = httpx2.URL(login_url(SETTINGS, NONCE))
    assert url.host == "www.epicgames.com"
    assert url.params["client_id"] == "the-client"
    assert url.params["redirect_uri"] == REDIRECT
    assert url.params["response_type"] == "code"
    assert url.params["scope"] == "basic_profile"
    assert url.params["state"] == NONCE
    assert SECRET not in str(url)


@pytest.mark.parametrize("route", ["/auth/epic", "/auth/epic/callback"])
def test_the_routes_do_not_exist_without_the_flag(route: str) -> None:
    settings = Settings(
        database_url="postgresql://nobody@127.0.0.1:1/nothing", database_timeout_s=0.2
    )
    with TestClient(create_app(settings), follow_redirects=False) as client:
        response = client.get(f"{PREFIX}{route}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_the_flag_needs_its_credentials() -> None:
    env = {"API_DATABASE_URL": "postgresql://x@localhost/x", "FEATURE_EPIC_LOGIN": "true"}
    with pytest.raises(SettingsError, match="EPIC_CLIENT_ID"):
        Settings.from_env(env)
    env |= {"EPIC_CLIENT_ID": "a", "EPIC_CLIENT_SECRET": "b"}
    with pytest.raises(SettingsError, match="EPIC_REDIRECT_URI"):
        Settings.from_env(env)
    settings = Settings.from_env(env | {"EPIC_REDIRECT_URI": REDIRECT})
    assert settings.epic_login
    assert settings.epic_client_secret == "b"


def test_credentials_are_not_needed_without_the_flag() -> None:
    settings = Settings.from_env({"API_DATABASE_URL": "postgresql://x@localhost/x"})
    assert not settings.epic_login


def test_secrets_stay_out_of_the_settings_text() -> None:
    settings = Settings(
        database_url="postgresql://user:db-password@host/db",
        session_secret="session-secret",
        epic_client_secret=SECRET,
    )
    for secret in ("db-password", "session-secret", SECRET):
        assert secret not in repr(settings)
