import os
from collections.abc import Iterator

import psycopg
import pytest

from ma_db.testing import Connection, Factory, role_url, temporary_database


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


@pytest.fixture(scope="session")
def worker_url(database: str) -> str:
    """The worker's own restricted role: the tests see the privileges production has."""
    return role_url(database, "ma_worker", os.environ.get("WORKER_DB_PASSWORD", "ma_worker_test"))


@pytest.fixture
def conn(database: str) -> Iterator[Connection]:
    """The tests' own view, as the schema's owner. Each test starts empty: a file one test has
    seen would otherwise be a duplicate for the next."""
    with psycopg.connect(database, autocommit=True) as connection:
        connection.execute("TRUNCATE jobs, matches, uploads, users, anonymous_sessions CASCADE")
        yield connection


@pytest.fixture
def worker_conn(worker_url: str) -> Iterator[Connection]:
    with psycopg.connect(worker_url, autocommit=True) as connection:
        yield connection


@pytest.fixture
def make(conn: Connection) -> Factory:
    return Factory(conn)
