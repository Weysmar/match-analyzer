"""Sign-in with Steam, through OpenID 2.0.

The browser brings Steam's answer back in its URL, so anyone can forge one: only Steam can confirm
it. Everything that can be refused locally is, before asking.
"""

import logging
import re
import urllib.parse
from collections.abc import Sequence

import httpx2
from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse

from ma_api import flow, signin
from ma_api.sessions import SettingsDep
from ma_api.settings import PREFIX, Settings

log = logging.getLogger("ma_api")

OPENID_NS = "http://specs.openid.net/auth/2.0"
_IDENTIFIER_SELECT = f"{OPENID_NS}/identifier_select"
_STEAM_ID = re.compile(r"https://steamcommunity\.com/openid/id/([0-9]{17})")
# What Steam has to vouch for. Its signature only covers the fields it lists: an answer could leave
# out the identity, and add one of its own that nothing checks.
_MUST_BE_SIGNED = {"op_endpoint", "claimed_id", "identity", "return_to", "response_nonce"}
_FLOW = "steam_flow"
_CALLBACK = "/auth/steam/callback"


def callback_url(settings: Settings, nonce: str) -> str:
    return f"{settings.site_url}{PREFIX}{_CALLBACK}?state={nonce}"


def login_url(settings: Settings, nonce: str) -> str:
    query = urllib.parse.urlencode(
        {
            "openid.ns": OPENID_NS,
            "openid.mode": "checkid_setup",
            "openid.return_to": callback_url(settings, nonce),
            "openid.realm": settings.site_url,
            "openid.identity": _IDENTIFIER_SELECT,
            "openid.claimed_id": _IDENTIFIER_SELECT,
        }
    )
    return f"{settings.steam_openid_url}?{query}"


def _local_refusal(params: dict[str, str], settings: Settings, nonce: str) -> str | None:
    """Why this answer cannot be right, without asking Steam. Names a rule, never a value."""
    if params.get("openid.ns") != OPENID_NS or params.get("openid.mode") != "id_res":
        return "not_a_positive_answer"
    if params.get("openid.op_endpoint") != settings.steam_openid_url:
        return "wrong_provider"
    if params.get("openid.return_to") != callback_url(settings, nonce):
        return "wrong_return_to"
    if not set(params.get("openid.signed", "").split(",")) >= _MUST_BE_SIGNED:
        return "unsigned_fields"
    if params.get("openid.claimed_id") != params.get("openid.identity"):
        return "identity_mismatch"
    if _STEAM_ID.fullmatch(params.get("openid.claimed_id", "")) is None:
        return "wrong_identity"
    return None


def _steam_confirms(client: httpx2.Client, params: dict[str, str], settings: Settings) -> bool:
    payload = {key: value for key, value in params.items() if key.startswith("openid.")}
    payload["openid.mode"] = "check_authentication"
    try:
        reply = client.post(settings.steam_openid_url, data=payload)
    except httpx2.HTTPError as error:
        log.warning("steam sign-in: %s while asking Steam", type(error).__name__)
        return False
    if reply.status_code != 200:
        log.warning("steam sign-in: Steam answered %d", reply.status_code)
        return False
    return "is_valid:true" in reply.text.splitlines()


def verified_steam_id(
    client: httpx2.Client,
    settings: Settings,
    query: Sequence[tuple[str, str]],
    nonce: str,
) -> str | None:
    """The SteamID64 this callback proves, or None."""
    params = dict(query)
    # A repeated field could show one value to these checks and another to Steam.
    if len(params) != len(query):
        refusal: str | None = "repeated_field"
    else:
        refusal = _local_refusal(params, settings, nonce)
    if refusal is not None:
        log.info("steam sign-in refused: %s", refusal)
        return None
    if not _steam_confirms(client, params, settings):
        log.info("steam sign-in refused: not_confirmed")
        return None
    match = _STEAM_ID.fullmatch(params["openid.claimed_id"])
    assert match is not None
    return match.group(1)


router = APIRouter()


@router.get("/auth/steam", status_code=303, response_class=RedirectResponse)
def start(request: Request, settings: SettingsDep, return_to: str = "/") -> Response:
    """Sends the browser to Steam, and remembers where to bring it back."""
    response, started = signin.begin(request, settings, _FLOW, return_to)
    response.headers["location"] = login_url(settings, started.nonce)
    return response


@router.get(_CALLBACK, status_code=303, response_class=RedirectResponse)
def callback(request: Request, settings: SettingsDep) -> Response:
    """Where Steam brings the browser back."""
    signin.count_attempt(request, settings)
    started = flow.read(request.cookies, settings, _FLOW)
    if started is None:
        log.info("steam sign-in refused: no_flow")
        return signin.failure(settings, _FLOW, "auth_failed")
    client: httpx2.Client = request.app.state.http
    steam_id = verified_steam_id(
        client, settings, request.query_params.multi_items(), started.nonce
    )
    if steam_id is None:
        return signin.failure(settings, _FLOW, "auth_failed")
    return signin.complete(request, settings, _FLOW, started, "steam", steam_id, None)
