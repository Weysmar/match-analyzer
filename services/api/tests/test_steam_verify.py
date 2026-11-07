"""Forged answers from a browser, and what Steam says about them. No database needed."""

import logging
from collections.abc import Callable

import httpx2
import pytest

from ma_api.settings import Settings
from ma_api.steam import OPENID_NS, callback_url, login_url, verified_steam_id

SITE = "https://example.test"
SETTINGS = Settings(database_url="unused", site_url=SITE)
NONCE = "the-nonce"
STEAM_ID = "76561190000000001"
IDENTITY = f"https://steamcommunity.com/openid/id/{STEAM_ID}"
CONFIRMED = f"ns:{OPENID_NS}\nis_valid:true\n"
SIGNED = "signed,op_endpoint,claimed_id,identity,return_to,response_nonce,assoc_handle"


def answer() -> dict[str, str]:
    return {
        "state": NONCE,
        "openid.ns": OPENID_NS,
        "openid.mode": "id_res",
        "openid.op_endpoint": SETTINGS.steam_openid_url,
        "openid.claimed_id": IDENTITY,
        "openid.identity": IDENTITY,
        "openid.return_to": callback_url(SETTINGS, NONCE),
        "openid.response_nonce": "2026-11-07T00:00:00Zabc",
        "openid.assoc_handle": "1234567890",
        "openid.signed": SIGNED,
        "openid.sig": "c2lnbmF0dXJl",
    }


class Steam:
    def __init__(self, reply: str = CONFIRMED, status: int = 200) -> None:
        self.reply = reply
        self.status = status
        self.requests: list[httpx2.Request] = []

    def client(self) -> httpx2.Client:
        return httpx2.Client(transport=httpx2.MockTransport(self._handle))

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        return httpx2.Response(self.status, text=self.reply)


def verify(steam: Steam, params: dict[str, str]) -> str | None:
    return verified_steam_id(steam.client(), SETTINGS, list(params.items()), NONCE)


def test_a_confirmed_answer_gives_the_steam_id() -> None:
    assert verify(Steam(), answer()) == STEAM_ID


def test_steam_gets_the_openid_fields_only() -> None:
    steam = Steam()
    verify(steam, {**answer(), "other": "value"})
    request = steam.requests[0]
    assert request.method == "POST"
    assert str(request.url) == SETTINGS.steam_openid_url
    body = httpx2.QueryParams(request.content.decode())
    assert body["openid.mode"] == "check_authentication"
    assert body["openid.sig"] == "c2lnbmF0dXJl"
    assert body["openid.claimed_id"] == IDENTITY
    assert "other" not in body
    assert "state" not in body


def without(field: str) -> Callable[[dict[str, str]], None]:
    def change(params: dict[str, str]) -> None:
        del params[field]

    return change


def with_value(field: str, value: str) -> Callable[[dict[str, str]], None]:
    return lambda params: params.__setitem__(field, value)


def both_identities(value: str) -> Callable[[dict[str, str]], None]:
    def change(params: dict[str, str]) -> None:
        params["openid.claimed_id"] = value
        params["openid.identity"] = value

    return change


@pytest.mark.parametrize(
    "forge",
    [
        pytest.param(with_value("openid.mode", "cancel"), id="cancelled"),
        pytest.param(with_value("openid.ns", "http://evil.test/"), id="other-namespace"),
        pytest.param(without("openid.mode"), id="no-mode"),
        pytest.param(with_value("openid.op_endpoint", "https://evil.test/"), id="other-provider"),
        pytest.param(without("openid.op_endpoint"), id="no-provider"),
        pytest.param(
            with_value("openid.return_to", "https://evil.test/callback"), id="other-return-to"
        ),
        pytest.param(
            with_value("openid.return_to", callback_url(SETTINGS, "another-nonce")),
            id="other-browser-nonce",
        ),
        pytest.param(without("openid.return_to"), id="no-return-to"),
        pytest.param(
            with_value("openid.signed", "signed,op_endpoint,return_to,response_nonce"),
            id="identity-not-signed",
        ),
        pytest.param(without("openid.signed"), id="nothing-signed"),
        pytest.param(
            with_value("openid.identity", f"{IDENTITY[:-1]}2"), id="identity-differs-from-claimed"
        ),
        pytest.param(without("openid.claimed_id"), id="no-claimed-id"),
        pytest.param(both_identities(f"https://evil.test/openid/id/{STEAM_ID}"), id="other-host"),
        pytest.param(
            both_identities(f"http://steamcommunity.com/openid/id/{STEAM_ID}"), id="not-https"
        ),
        pytest.param(both_identities(f"{IDENTITY}/"), id="trailing-slash"),
        pytest.param(both_identities(f"{IDENTITY}?x=1"), id="trailing-query"),
        pytest.param(both_identities(IDENTITY[:-1]), id="too-short"),
        pytest.param(both_identities(f"{IDENTITY[:-1]}٣"), id="other-digits"),
    ],
)
def test_a_forged_answer_never_reaches_steam(forge: Callable[[dict[str, str]], None]) -> None:
    params = answer()
    forge(params)
    steam = Steam()
    assert verify(steam, params) is None
    assert steam.requests == []


def test_a_repeated_field_is_refused() -> None:
    query = [*answer().items(), ("openid.claimed_id", "https://evil.test/")]
    steam = Steam()
    assert verified_steam_id(steam.client(), SETTINGS, query, NONCE) is None
    assert steam.requests == []


@pytest.mark.parametrize(
    "reply",
    [
        f"ns:{OPENID_NS}\nis_valid:false\n",
        "",
        "is_valid:true and more\n",
        "other:is_valid:true\n",
        "IS_VALID:TRUE\n",
    ],
)
def test_steam_must_confirm(reply: str) -> None:
    assert verify(Steam(reply), answer()) is None


def test_a_failing_steam_refuses() -> None:
    assert verify(Steam(status=500), answer()) is None


def test_steam_out_of_reach_refuses() -> None:
    def fail(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("unreachable", request=request)

    client = httpx2.Client(transport=httpx2.MockTransport(fail))
    assert verified_steam_id(client, SETTINGS, list(answer().items()), NONCE) is None


def test_the_log_never_holds_an_identity(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="ma_api"):
        verify(Steam("is_valid:false\n"), answer())
        params = answer()
        params["openid.op_endpoint"] = "https://evil.test/"
        verify(Steam(), params)
    assert "refused" in caplog.text
    assert STEAM_ID not in caplog.text
    assert "evil.test" not in caplog.text


def test_the_login_url_asks_steam_to_come_back_here() -> None:
    url = httpx2.URL(login_url(SETTINGS, NONCE))
    assert str(url.copy_with(query=None)) == "https://steamcommunity.com/openid/login"
    assert url.params["openid.mode"] == "checkid_setup"
    assert url.params["openid.realm"] == SITE
    assert url.params["openid.return_to"] == f"{SITE}/api/v1/auth/steam/callback?state={NONCE}"
    assert url.params["openid.identity"] == f"{OPENID_NS}/identifier_select"
    assert url.params["openid.claimed_id"] == f"{OPENID_NS}/identifier_select"
