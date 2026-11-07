"""Accounts: a user is created by a first sign-in, and can hold one account per provider."""

import uuid

from ma_api.db import Connection

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
