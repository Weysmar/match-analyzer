"""Who is asking: a signed-in user, an anonymous session or nobody.

A session is a random token in a cookie. The database only holds its hash, so a read of the table
gives nobody a way in, and deleting the row ends the session.
"""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from ma_api.db import Connection, ConnectionDep
from ma_api.errors import ApiError
from ma_api.owner import Owner
from ma_api.settings import Settings

_SESSION_COOKIE = "session"
_ANONYMOUS_COOKIE = "anon"


def cookie_name(settings: Settings, base: str) -> str:
    """`__Host-` binds a cookie to this exact host over https. It needs `Secure`, so it cannot be
    used on the development server."""
    return f"__Host-{base}" if settings.secure_cookies else base


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


def set_cookie(
    response: Response, settings: Settings, base: str, value: str, max_age_s: int
) -> None:
    response.set_cookie(
        cookie_name(settings, base),
        value,
        max_age=max_age_s,
        path="/",
        secure=settings.secure_cookies,
        httponly=True,
        samesite="lax",
    )


def _delete_cookie(response: Response, settings: Settings, base: str) -> None:
    response.delete_cookie(
        cookie_name(settings, base),
        path="/",
        secure=settings.secure_cookies,
        httponly=True,
        samesite="lax",
    )


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


SettingsDep = Annotated[Settings, Depends(get_settings)]


@dataclass(frozen=True)
class Identity:
    owner: Owner | None = None

    @property
    def kind(self) -> str:
        if self.owner is None:
            return "none"
        return "user" if self.owner.is_user else "anonymous"


def _user_of(connection: Connection, token: str) -> uuid.UUID | None:
    row = connection.execute(
        "SELECT user_id FROM auth_sessions WHERE token_hash = %s AND expires_at > now()",
        (token_hash(token),),
    ).fetchone()
    return None if row is None else row[0]


def _anonymous_of(connection: Connection, token: str) -> uuid.UUID | None:
    row = connection.execute(
        "SELECT id FROM anonymous_sessions WHERE token_hash = %s AND expires_at > now()",
        (token_hash(token),),
    ).fetchone()
    return None if row is None else row[0]


def identify(connection: Connection, settings: Settings, cookies: dict[str, str]) -> Identity:
    """A signed-in user wins over an anonymous session. A forged or expired cookie is nobody."""
    token = cookies.get(cookie_name(settings, _SESSION_COOKIE))
    if token:
        user = _user_of(connection, token)
        if user is not None:
            return Identity(Owner(user_id=user))
    token = cookies.get(cookie_name(settings, _ANONYMOUS_COOKIE))
    if token:
        session = _anonymous_of(connection, token)
        if session is not None:
            return Identity(Owner(anonymous_session_id=session))
    return Identity()


def anonymous_session_of(
    connection: Connection, settings: Settings, cookies: dict[str, str]
) -> uuid.UUID | None:
    """Whatever else the browser holds: a sign-in takes over the anonymous session as well."""
    token = cookies.get(cookie_name(settings, _ANONYMOUS_COOKIE))
    return _anonymous_of(connection, token) if token else None


def clear_anonymous_cookie(response: Response, settings: Settings) -> None:
    _delete_cookie(response, settings, _ANONYMOUS_COOKIE)


def get_identity(request: Request, connection: ConnectionDep, settings: SettingsDep) -> Identity:
    return identify(connection, settings, request.cookies)


IdentityDep = Annotated[Identity, Depends(get_identity)]


def require_owner(identity: Identity) -> Owner:
    if identity.owner is None:
        raise ApiError(401, "not_signed_in")
    return identity.owner


def ensure_owner(
    connection: Connection, settings: Settings, identity: Identity, response: Response
) -> Owner:
    """The caller's owner, opening an anonymous session for a first upload: that is the only thing
    that creates one, so that visiting the site leaves nothing behind."""
    if identity.owner is not None:
        return identity.owner
    token = new_token()
    row = connection.execute(
        "INSERT INTO anonymous_sessions (token_hash, expires_at) "
        "VALUES (%s, now() + make_interval(days => %s)) RETURNING id",
        (token_hash(token), settings.anonymous_session_ttl_days),
    ).fetchone()
    assert row is not None
    days = settings.anonymous_session_ttl_days
    set_cookie(response, settings, _ANONYMOUS_COOKIE, token, days * 86_400)
    return Owner(anonymous_session_id=row[0])


def open_user_session(
    connection: Connection, settings: Settings, user: uuid.UUID, response: Response
) -> None:
    token = new_token()
    connection.execute(
        "INSERT INTO auth_sessions (token_hash, user_id, expires_at) "
        "VALUES (%s, %s, now() + make_interval(days => %s))",
        (token_hash(token), user, settings.session_ttl_days),
    )
    set_cookie(response, settings, _SESSION_COOKIE, token, settings.session_ttl_days * 86_400)


router = APIRouter()


@router.post("/auth/logout", status_code=204)
def logout(request: Request, connection: ConnectionDep, settings: SettingsDep) -> Response:
    """Deletes the session itself: a copy of the cookie stops working as well."""
    token = request.cookies.get(cookie_name(settings, _SESSION_COOKIE))
    if token:
        connection.execute("DELETE FROM auth_sessions WHERE token_hash = %s", (token_hash(token),))
    response = Response(status_code=204)
    _delete_cookie(response, settings, _SESSION_COOKIE)
    return response


@router.get("/me")
def me(
    connection: ConnectionDep, settings: SettingsDep, identity: IdentityDep
) -> dict[str, object]:
    """Who the site is talking to, and which sign-ins it offers. No platform id in here."""
    user: dict[str, object] | None = None
    linked: list[dict[str, object]] = []
    if identity.owner is not None and identity.owner.user_id is not None:
        row = connection.execute(
            "SELECT id, display_name, locale FROM users WHERE id = %s", (identity.owner.user_id,)
        ).fetchone()
        if row is not None:
            user = {"id": str(row[0]), "display_name": row[1], "locale": row[2]}
        accounts = connection.execute(
            "SELECT provider, display_name FROM linked_accounts WHERE user_id = %s "
            "ORDER BY provider",
            (identity.owner.user_id,),
        ).fetchall()
        linked = [{"provider": account[0], "display_name": account[1]} for account in accounts]
    return {
        "kind": identity.kind,
        "user": user,
        "linked_accounts": linked,
        "features": {"epic_login": settings.epic_login},
    }
