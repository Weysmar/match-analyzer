"""Who owns what. Every read of a match goes through `owned_match`: section 11 of CLAUDE.md forbids
showing a match, and the players in it, to anyone who did not bring it."""

import uuid
from dataclasses import dataclass
from typing import Any

from psycopg import sql
from psycopg.rows import dict_row

from ma_api.db import Connection
from ma_api.errors import not_found


@dataclass(frozen=True)
class Owner:
    """A signed-in user, or an anonymous session: never both."""

    user_id: uuid.UUID | None = None
    anonymous_session_id: uuid.UUID | None = None

    def __post_init__(self) -> None:
        if (self.user_id is None) == (self.anonymous_session_id is None):
            raise ValueError("an owner is a user or an anonymous session")

    @property
    def is_user(self) -> bool:
        return self.user_id is not None

    @property
    def condition(self) -> sql.Composed:
        """`<column> = <id>`, for the tables holding both owner columns."""
        column = "user_id" if self.is_user else "anonymous_session_id"
        value = self.user_id if self.is_user else self.anonymous_session_id
        return sql.SQL("{} = {}").format(sql.Identifier(column), sql.Literal(value))


def owned_match(connection: Connection, owner: Owner, match_id: uuid.UUID) -> dict[str, Any]:
    """The owner's link to this match. A match they do not own looks like one that does not exist,
    so that nobody can test which matches are known."""
    query = sql.SQL("SELECT * FROM user_matches WHERE match_id = %s AND {}").format(owner.condition)
    with connection.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute(query, (match_id,)).fetchone()
    if row is None:
        raise not_found()
    return row
