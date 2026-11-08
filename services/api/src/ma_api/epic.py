"""Sign-in with Epic, through OAuth, behind `FEATURE_EPIC_LOGIN`.

Epic's documentation confirms the authorization, the token and `account_id`, which is what identity
rests on. `userInfo` only gives a name to display: when it fails, the sign-in goes on without one.
"""

import hmac
import logging
import re
import urllib.parse
from collections.abc import Sequence
from typing import Any

import httpx2
from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse

from ma_api import flow, signin
from ma_api.errors import not_found
from ma_api.sessions import SettingsDep
from ma_api.settings import Settings

log = logging.getLogger("ma_api")

_FLOW = "epic_flow"
_SCOPE = "basic_profile"
_ACCOUNT_ID = re.compile(r"[0-9A-Za-z]{1,64}")
_CODE_MAX = 2048
_NAME_MAX = 64


def login_url(settings: Settings, nonce: str) -> str:
    query = urllib.parse.urlencode(
        {
            "client_id": settings.epic_client_id,
            "redirect_uri": settings.epic_redirect_uri,
            "response_type": "code",
            "scope": _SCOPE,
            "state": nonce,
        }
    )
    return f"{settings.epic_authorize_url}?{query}"


def _code_from(query: Sequence[tuple[str, str]], nonce: str) -> str | None:
    """The authorization code in this callback, when it belongs to this browser's flow."""
    params = dict(query)
    # A repeated field could show one value to these checks and another later on.
    if len(params) != len(query):
        refusal = "repeated_field"
    elif not hmac.compare_digest(params.get("state", "").encode(), nonce.encode()):
        refusal = "wrong_state"
    elif "error" in params:
        refusal = "denied"
    elif not 0 < len(params.get("code", "")) <= _CODE_MAX:
        refusal = "no_code"
    else:
        return params["code"]
    log.info("epic sign-in refused: %s", refusal)
    return None


def _json_object(reply: httpx2.Response) -> dict[str, Any] | None:
    if reply.status_code != 200:
        log.warning("epic sign-in: Epic answered %d", reply.status_code)
        return None
    try:
        body = reply.json()
    except ValueError:
        log.warning("epic sign-in: Epic's answer is not JSON")
        return None
    return body if isinstance(body, dict) else None


def _exchange(client: httpx2.Client, settings: Settings, code: str) -> tuple[str, str] | None:
    """The access token and the account id for this code. Epic checks the code: nobody else can."""
    try:
        reply = client.post(
            settings.epic_token_url,
            auth=(settings.epic_client_id, settings.epic_client_secret),
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.epic_redirect_uri,
            },
        )
    except httpx2.HTTPError as error:
        log.warning("epic sign-in: %s while asking Epic", type(error).__name__)
        return None
    body = _json_object(reply)
    if body is None:
        return None
    token, account_id = body.get("access_token"), body.get("account_id")
    if not isinstance(token, str) or not token:
        log.warning("epic sign-in: no access token")
        return None
    if not isinstance(account_id, str) or _ACCOUNT_ID.fullmatch(account_id) is None:
        log.warning("epic sign-in: no usable account id")
        return None
    return token, account_id


def _display_name(
    client: httpx2.Client, settings: Settings, token: str, account_id: str
) -> str | None:
    try:
        reply = client.get(settings.epic_userinfo_url, headers={"Authorization": f"Bearer {token}"})
    except httpx2.HTTPError as error:
        log.warning("epic sign-in: %s while asking for the name", type(error).__name__)
        return None
    body = _json_object(reply)
    if body is None or body.get("sub") != account_id:
        return None
    name = body.get("preferred_username")
    return name if isinstance(name, str) and 0 < len(name) <= _NAME_MAX else None


def verified_account(
    client: httpx2.Client,
    settings: Settings,
    query: Sequence[tuple[str, str]],
    nonce: str,
) -> tuple[str, str | None] | None:
    """The account id this callback proves and its name if known, or None."""
    code = _code_from(query, nonce)
    if code is None:
        return None
    exchanged = _exchange(client, settings, code)
    if exchanged is None:
        return None
    token, account_id = exchanged
    return account_id, _display_name(client, settings, token, account_id)


def _require_enabled(settings: Settings) -> None:
    if not settings.epic_login:
        raise not_found()


router = APIRouter()


@router.get("/auth/epic", status_code=303, response_class=RedirectResponse)
def start(request: Request, settings: SettingsDep, return_to: str = "/") -> Response:
    """Sends the browser to Epic, and remembers where to bring it back."""
    _require_enabled(settings)
    response, started = signin.begin(request, settings, _FLOW, return_to)
    response.headers["location"] = login_url(settings, started.nonce)
    return response


@router.get("/auth/epic/callback", status_code=303, response_class=RedirectResponse)
def callback(request: Request, settings: SettingsDep) -> Response:
    """Where Epic brings the browser back."""
    _require_enabled(settings)
    signin.count_attempt(request, settings)
    started = flow.read(request.cookies, settings, _FLOW)
    if started is None:
        log.info("epic sign-in refused: no_flow")
        return signin.failure(settings, _FLOW, "auth_failed")
    client: httpx2.Client = request.app.state.http
    verified = verified_account(client, settings, request.query_params.multi_items(), started.nonce)
    if verified is None:
        return signin.failure(settings, _FLOW, "auth_failed")
    account_id, display_name = verified
    return signin.complete(request, settings, _FLOW, started, "epic", account_id, display_name)
