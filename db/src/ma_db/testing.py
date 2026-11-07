"""For tests that need the database: this package's, the API's and the worker's."""

import hashlib
import urllib.parse
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, cast

import psycopg
from psycopg import sql

from ma_db import migrate

type Connection = psycopg.Connection[tuple[Any, ...]]


@contextmanager
def temporary_database(admin_url: str, *, migrated: bool = True) -> Iterator[str]:
    """A database of its own, dropped afterwards. Yields its URL."""
    name = f"ma_test_{uuid.uuid4().hex}"
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    url = urllib.parse.urlsplit(admin_url)._replace(path=f"/{name}").geturl()
    try:
        if migrated:
            migrate.upgrade(url)
        yield url
    finally:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


class Factory:
    """Rows with sensible defaults, to keep tests about the one thing they check."""

    def __init__(self, connection: Connection) -> None:
        self.connection = connection
        self._count = 0

    def _next(self) -> int:
        self._count += 1
        return self._count

    def _one[T](self, kind: type[T], query: str, *parameters: object) -> T:
        row = self.connection.execute(query.encode(), parameters).fetchone()
        assert row is not None
        return cast(T, row[0])

    def user(self, name: str = "someone") -> uuid.UUID:
        return self._one(
            uuid.UUID, "INSERT INTO users (display_name) VALUES (%s) RETURNING id", name
        )

    def linked_account(self, user_id: uuid.UUID, provider: str, account_id: str) -> int:
        return self._one(
            int,
            "INSERT INTO linked_accounts (user_id, provider, provider_account_id) "
            "VALUES (%s, %s, %s) RETURNING id",
            user_id,
            provider,
            account_id,
        )

    def anonymous_session(self) -> uuid.UUID:
        token = f"token-{self._next()}-{uuid.uuid4()}".encode()
        return self._one(
            uuid.UUID,
            "INSERT INTO anonymous_sessions (token_hash, expires_at) "
            "VALUES (%s, now() + interval '1 day') RETURNING id",
            hashlib.sha256(token).digest(),
        )

    def match(self, status: str = "ready") -> uuid.UUID:
        key = hashlib.sha256(f"match-{self._next()}-{uuid.uuid4()}".encode()).hexdigest()
        return self._one(
            uuid.UUID,
            "INSERT INTO matches (dedupe_key, status, parser_version) "
            "VALUES (%s, %s, '0.1.1') RETURNING id",
            key,
            status,
        )

    def player(
        self,
        match_id: uuid.UUID,
        *,
        platform: str = "steam",
        platform_id: str | None = None,
        team: int = 0,
    ) -> int:
        return self._one(
            int,
            "INSERT INTO match_players (match_id, platform, platform_id, display_name, team) "
            "VALUES (%s, %s, %s, 'a player', %s) RETURNING id",
            match_id,
            platform,
            platform_id if platform_id is not None else str(self._next()),
            team,
        )

    def user_match(
        self,
        match_id: uuid.UUID,
        *,
        user_id: uuid.UUID | None = None,
        anonymous_session_id: uuid.UUID | None = None,
        match_player_id: int | None = None,
        identity_source: str = "none",
        verified: bool = False,
    ) -> int:
        return self._one(
            int,
            "INSERT INTO user_matches (user_id, anonymous_session_id, match_id, match_player_id, "
            "identity_source, verified) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            user_id,
            anonymous_session_id,
            match_id,
            match_player_id,
            identity_source,
            verified,
        )

    def upload(
        self,
        *,
        user_id: uuid.UUID | None = None,
        anonymous_session_id: uuid.UUID | None = None,
        match_id: uuid.UUID | None = None,
    ) -> uuid.UUID:
        upload_id = uuid.uuid4()
        return self._one(
            uuid.UUID,
            "INSERT INTO uploads (id, user_id, anonymous_session_id, file_name, declared_size, "
            "incoming_key, match_id) VALUES (%s, %s, %s, 'a.replay', 100, %s, %s) RETURNING id",
            upload_id,
            user_id,
            anonymous_session_id,
            f"incoming/{upload_id}",
            match_id,
        )

    def metric(
        self, match_player_id: int, metric_id: str = "boost.avg", value: float = 1.0
    ) -> None:
        self.connection.execute(
            "INSERT INTO player_match_metrics "
            "(match_player_id, metric_id, value, analysis_version) VALUES (%s, %s, %s, '1')",
            (match_player_id, metric_id, value),
        )


def count(connection: Connection, query: str, *parameters: object) -> int:
    row = connection.execute(query.encode(), parameters).fetchone()
    assert row is not None
    return int(row[0])
