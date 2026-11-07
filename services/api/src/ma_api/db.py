"""Connections to PostgreSQL, with the restricted role `ma_api`."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated, Any

import psycopg
from fastapi import Depends, Request
from psycopg_pool import ConnectionPool

type Connection = psycopg.Connection[tuple[Any, ...]]


class Database:
    def __init__(self, url: str, *, timeout_s: float = 5.0, max_size: int = 10) -> None:
        self.timeout_s = timeout_s
        self.pool = ConnectionPool(
            url,
            min_size=1,
            max_size=max_size,
            timeout=timeout_s,
            open=False,
        )

    def open(self) -> None:
        # Without waiting: the API starts, and reports through /health, when PostgreSQL is down.
        self.pool.open(wait=False)

    def close(self) -> None:
        self.pool.close()

    @contextmanager
    def transaction(self) -> Iterator[Connection]:
        """Commits at the end, rolls back on an exception."""
        with self.pool.connection() as connection:
            yield connection


def get_connection(request: Request) -> Iterator[Connection]:
    database: Database = request.app.state.database
    with database.transaction() as connection:
        yield connection


# "function": the transaction commits before the response leaves, so a client that gets an answer
# can read what it just wrote. With the default scope, the commit would come after the response.
ConnectionDep = Annotated[Connection, Depends(get_connection, scope="function")]
