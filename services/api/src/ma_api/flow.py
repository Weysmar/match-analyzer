"""The short memory of a sign-in, between leaving for a provider and coming back.

It lives in a signed cookie of the browser that started the sign-in. A provider's answer has to
carry the same nonce, so that nobody can sign a victim into the attacker's account by sending them
a ready-made callback link. Without the signature, a visitor could also rewrite where they get sent
back to.
"""

import base64
import hashlib
import hmac
import json
import secrets
import time
import urllib.parse
from dataclasses import dataclass

from fastapi import Response

from ma_api.sessions import cookie_name, set_cookie
from ma_api.settings import Settings

TTL_S = 600
_RETURN_TO_MAX = 512


@dataclass(frozen=True)
class Flow:
    nonce: str
    return_to: str


def safe_return_to(value: str) -> str | None:
    """`value` if it can only lead to a page of this site, else None: it ends up in a redirect, and
    `//evil.test` or `/\\evil.test` are other sites to a browser."""
    if not value.startswith("/") or value.startswith("//") or len(value) > _RETURN_TO_MAX:
        return None
    if "\\" in value or not value.isprintable():
        return None
    parts = urllib.parse.urlsplit(value)
    return None if parts.scheme or parts.netloc else value


def _signature(settings: Settings, payload: str) -> str:
    # The prefix keeps this signature apart from the secret's other uses.
    message = f"flow:{payload}".encode()
    return hmac.new(settings.session_secret.encode(), message, hashlib.sha256).hexdigest()


def encode(settings: Settings, flow: Flow, expires_at: float) -> str:
    content = {"nonce": flow.nonce, "return_to": flow.return_to, "expires_at": expires_at}
    payload = base64.urlsafe_b64encode(json.dumps(content).encode()).decode()
    return f"{payload}.{_signature(settings, payload)}"


def decode(settings: Settings, cookie: str, now: float) -> Flow | None:
    """The flow in this cookie, unless it was altered or is too old."""
    payload, _, signature = cookie.partition(".")
    if not hmac.compare_digest(signature.encode(), _signature(settings, payload).encode()):
        return None
    # Signed by this server: what follows cannot be malformed.
    content = json.loads(base64.urlsafe_b64decode(payload))
    if content["expires_at"] <= now:
        return None
    return Flow(content["nonce"], content["return_to"])


def start(response: Response, settings: Settings, name: str, return_to: str) -> Flow:
    flow = Flow(secrets.token_urlsafe(32), return_to)
    set_cookie(response, settings, name, encode(settings, flow, time.time() + TTL_S), TTL_S)
    return flow


def read(cookies: dict[str, str], settings: Settings, name: str) -> Flow | None:
    cookie = cookies.get(cookie_name(settings, name))
    return None if cookie is None else decode(settings, cookie, time.time())


def finish(response: Response, settings: Settings, name: str) -> None:
    """A flow serves once, whatever its outcome."""
    response.delete_cookie(
        cookie_name(settings, name),
        path="/",
        secure=settings.secure_cookies,
        httponly=True,
        samesite="lax",
    )
