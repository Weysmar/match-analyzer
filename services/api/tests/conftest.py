import os
from collections.abc import Iterator

import psycopg
import pytest
from fastapi.testclient import TestClient

from ma_api.app import create_app
from ma_api.settings import Settings
from ma_db.testing import Connection, Factory, role_url, temporary_database

SITE = "http://testserver"


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
def api_url(database: str) -> str:
    """The API's own restricted role: the tests see the privileges production has."""
    return role_url(database, "ma_api", os.environ.get("API_DB_PASSWORD", "ma_api_test"))


@pytest.fixture
def settings(api_url: str) -> Settings:
    return Settings(database_url=api_url, site_url=SITE, session_secret="test-secret")


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings), base_url=SITE, headers={"Origin": SITE}) as test_client:
        yield test_client


@pytest.fixture
def conn(database: str) -> Iterator[Connection]:
    """The tests' own view, as the schema's owner. It commits: the API has to see these rows."""
    with psycopg.connect(database, autocommit=True) as connection:
        yield connection


@pytest.fixture
def make(conn: Connection) -> Factory:
    return Factory(conn)


@pytest.fixture
def clean_limits(conn: Connection) -> Iterator[None]:
    conn.execute("DELETE FROM rate_limit_buckets")
    yield
    conn.execute("DELETE FROM rate_limit_buckets")
