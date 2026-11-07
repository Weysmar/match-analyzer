import os
from collections.abc import Iterator

import psycopg
import pytest

from ma_db.testing import Connection, Factory, temporary_database


@pytest.fixture(scope="session")
def admin_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set: run `just dev-up`, then `just test-db`")
    return url


@pytest.fixture(scope="session")
def database(admin_url: str) -> Iterator[str]:
    with temporary_database(admin_url) as url:
        yield url


@pytest.fixture
def conn(database: str) -> Iterator[Connection]:
    """A connection whose work is undone after the test."""
    with (
        psycopg.connect(database) as connection,
        connection.transaction(force_rollback=True),
    ):
        yield connection


@pytest.fixture
def make(conn: Connection) -> Factory:
    return Factory(conn)
