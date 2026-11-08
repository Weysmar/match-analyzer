"""Accounts: a user is created by a first sign-in, and can hold one account per provider."""

import uuid

from fastapi import APIRouter, Request, Response

from ma_api import sessions
from ma_api.db import Connection, ConnectionDep
from ma_api.errors import ApiError
from ma_api.sessions import IdentityDep, SettingsDep

# Steam gives no name without a Web API key, which V1 does not use.
DEFAULT_DISPLAY_NAME = "Player"


class AccountAlreadyLinkedError(Exception):
    """This provider account belongs to someone else, or the user already has another one. Accounts
    are not merged in V1 (D12)."""


def _owner_of(connection: Connection, provider: str, account_id: str) -> uuid.UUID | None:
    row = connection.execute(
        "SELECT user_id FROM linked_accounts WHERE provider = %s AND provider_account_id = %s",
        (provider, account_id),
    ).fetchone()
    return None if row is None else row[0]


def _link(
    connection: Connection,
    user: uuid.UUID,
    provider: str,
    account_id: str,
    display_name: str | None,
) -> bool:
    """False when a unique constraint stands in the way, with nothing written."""
    row = connection.execute(
        "INSERT INTO linked_accounts (user_id, provider, provider_account_id, display_name) "
        "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING RETURNING id",
        (user, provider, account_id, display_name),
    ).fetchone()
    return row is not None


def _create(
    connection: Connection, provider: str, account_id: str, display_name: str | None
) -> uuid.UUID:
    row = connection.execute(
        "INSERT INTO users (display_name) VALUES (%s) RETURNING id",
        (display_name or DEFAULT_DISPLAY_NAME,),
    ).fetchone()
    assert row is not None
    user: uuid.UUID = row[0]
    if _link(connection, user, provider, account_id, display_name):
        return user
    # Two first sign-ins of the same account at once, and the other one won.
    connection.execute("DELETE FROM users WHERE id = %s", (user,))
    owner = _owner_of(connection, provider, account_id)
    assert owner is not None
    return owner


def sign_in(
    connection: Connection,
    provider: str,
    account_id: str,
    display_name: str | None,
    current_user: uuid.UUID | None,
) -> uuid.UUID:
    """The user this provider account signs in. Already signed in, it links the account to them."""
    owner = _owner_of(connection, provider, account_id)
    if current_user is None:
        return owner or _create(connection, provider, account_id, display_name)
    if owner is None and _link(connection, current_user, provider, account_id, display_name):
        return current_user
    if _owner_of(connection, provider, account_id) == current_user:
        return current_user
    raise AccountAlreadyLinkedError


def _queue_cleanup(connection: Connection, matches: list[uuid.UUID]) -> None:
    """A match is only deleted once nobody owns it: that is for the worker to check, since someone
    else may hold it, or bring it back in the meantime."""
    connection.execute(
        "INSERT INTO jobs (kind, payload) "
        "SELECT 'gc_match', jsonb_build_object('match_id', match_id) FROM unnest(%s::uuid[]) "
        "AS match_id",
        (matches,),
    )


def _matches_of_session(connection: Connection, session: uuid.UUID) -> list[uuid.UUID]:
    rows = connection.execute(
        "SELECT match_id FROM user_matches WHERE anonymous_session_id = %s", (session,)
    ).fetchall()
    return [row[0] for row in rows]


router = APIRouter()


@router.delete("/me", status_code=202, response_class=Response)
def erase_account(
    request: Request, connection: ConnectionDep, settings: SettingsDep, identity: IdentityDep
) -> Response:
    """The right to erasure: the account, its links and its sessions go at once, along with this
    browser's anonymous session. Matches follow if nobody else holds them."""
    user = None if identity.owner is None else identity.owner.user_id
    if user is None:
        raise ApiError(401, "not_signed_in")
    rows = connection.execute(
        "SELECT match_id FROM user_matches WHERE user_id = %s", (user,)
    ).fetchall()
    matches = [row[0] for row in rows]
    anonymous = sessions.anonymous_session_of(connection, settings, request.cookies)
    if anonymous is not None:
        matches += _matches_of_session(connection, anonymous)
        connection.execute("DELETE FROM anonymous_sessions WHERE id = %s", (anonymous,))
    connection.execute("DELETE FROM users WHERE id = %s", (user,))
    _queue_cleanup(connection, matches)
    response = Response(status_code=202)
    sessions.clear_user_cookie(response, settings)
    sessions.clear_anonymous_cookie(response, settings)
    return response


@router.delete("/me/anonymous", status_code=202, response_class=Response)
def erase_anonymous_session(
    request: Request, connection: ConnectionDep, settings: SettingsDep
) -> Response:
    """The same without an account. With no session there is nothing to do, which is fine."""
    anonymous = sessions.anonymous_session_of(connection, settings, request.cookies)
    if anonymous is not None:
        matches = _matches_of_session(connection, anonymous)
        connection.execute("DELETE FROM anonymous_sessions WHERE id = %s", (anonymous,))
        _queue_cleanup(connection, matches)
    response = Response(status_code=202)
    sessions.clear_anonymous_cookie(response, settings)
    return response
