"""Sessions, ownership and rate limits, against PostgreSQL with the API's own role."""

import hashlib
import uuid
from collections.abc import Iterator
from datetime import timedelta

import httpx2
import psycopg
import pytest
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient

from ma_api import owner as owner_module
from ma_api import ratelimit, sessions
from ma_api.app import create_app
from ma_api.db import ConnectionDep
from ma_api.errors import ApiError
from ma_api.owner import Owner
from ma_api.settings import PREFIX, Settings
from ma_db.testing import Connection, Factory, count

pytestmark = pytest.mark.db

ME = f"{PREFIX}/me"
SITE = "http://testserver"


def login(conn: Connection, user: uuid.UUID, *, valid: bool = True) -> str:
    token = sessions.new_token()
    conn.execute(
        "INSERT INTO auth_sessions (token_hash, user_id, expires_at) VALUES (%s, %s, now() + %s)",
        (sessions.token_hash(token), user, timedelta(days=1 if valid else -1)),
    )
    return token


def anonymous(conn: Connection, *, valid: bool = True) -> tuple[uuid.UUID, str]:
    token = sessions.new_token()
    row = conn.execute(
        "INSERT INTO anonymous_sessions (token_hash, expires_at) VALUES (%s, now() + %s) "
        "RETURNING id",
        (sessions.token_hash(token), timedelta(days=1 if valid else -1)),
    ).fetchone()
    assert row is not None
    return row[0], token


def me_with(client: TestClient, **cookies: str) -> httpx2.Response:
    client.cookies.clear()
    for name, value in cookies.items():
        client.cookies.set(name, value)
    return client.get(ME)


def test_nobody_by_default(client: TestClient) -> None:
    body = client.get(ME).json()
    assert body == {
        "kind": "none",
        "user": None,
        "linked_accounts": [],
        "features": {"epic_login": False},
    }


def test_visiting_creates_no_session(client: TestClient, conn: Connection) -> None:
    before = count(conn, "SELECT count(*) FROM anonymous_sessions")
    response = client.get(ME)
    assert "set-cookie" not in response.headers
    assert count(conn, "SELECT count(*) FROM anonymous_sessions") == before


def test_health_with_the_database(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_a_signed_in_user(client: TestClient, conn: Connection, make: Factory) -> None:
    user = make.user("Someone")
    make.linked_account(user, "steam", "76561190000000001")
    token = login(conn, user)
    response = me_with(client, session=token)
    body = response.json()
    assert body["kind"] == "user"
    assert body["user"]["display_name"] == "Someone"
    assert body["linked_accounts"] == [{"provider": "steam", "display_name": None}]
    # The account's platform id never goes out.
    assert "76561190000000001" not in response.text


def test_an_anonymous_session(client: TestClient, conn: Connection) -> None:
    _, token = anonymous(conn)
    assert me_with(client, anon=token).json()["kind"] == "anonymous"


def test_a_user_wins_over_an_anonymous_session(
    client: TestClient, conn: Connection, make: Factory
) -> None:
    _, anon = anonymous(conn)
    token = login(conn, make.user())
    assert me_with(client, anon=anon, session=token).json()["kind"] == "user"


@pytest.mark.parametrize("cookie", ["session", "anon"])
def test_a_forged_cookie_is_nobody(client: TestClient, cookie: str) -> None:
    assert me_with(client, **{cookie: "forged"}).json()["kind"] == "none"


def test_an_expired_session_is_nobody(client: TestClient, conn: Connection, make: Factory) -> None:
    token = login(conn, make.user(), valid=False)
    assert me_with(client, session=token).json()["kind"] == "none"


def test_an_expired_anonymous_session_is_nobody(client: TestClient, conn: Connection) -> None:
    _, token = anonymous(conn, valid=False)
    assert me_with(client, anon=token).json()["kind"] == "none"


def test_a_hash_stolen_from_the_table_is_not_a_cookie(
    client: TestClient, conn: Connection, make: Factory
) -> None:
    token = login(conn, make.user())
    stolen = hashlib.sha256(token.encode()).hexdigest()
    assert me_with(client, session=stolen).json()["kind"] == "none"


def test_a_token_is_never_stored_in_clear(conn: Connection, make: Factory) -> None:
    token = login(conn, make.user())
    assert (
        count(conn, "SELECT count(*) FROM auth_sessions WHERE token_hash = %s", token.encode()) == 0
    )


def extended_app(settings: Settings) -> FastAPI:
    """Routes for what later steps build on, each going through the real dependencies."""
    app = create_app(settings)

    @app.post("/test/first-upload")
    def first_upload(
        connection: ConnectionDep,
        identity: sessions.IdentityDep,
        response: Response,
    ) -> dict[str, str]:
        owner = sessions.ensure_owner(connection, settings, identity, response)
        return {"owner": str(owner.anonymous_session_id or owner.user_id)}

    @app.post("/test/fail-after-write")
    def fail(connection: ConnectionDep) -> None:
        connection.execute("INSERT INTO users (display_name) VALUES ('rolled back')")
        raise ApiError(409, "conflict")

    @app.post("/test/write")
    def write(connection: ConnectionDep) -> dict[str, int]:
        connection.execute("INSERT INTO users (display_name) VALUES ('committed')")
        return {"ok": 1}

    @app.post("/test/limited")
    def limited(connection: ConnectionDep, request: Request) -> dict[str, str]:
        ratelimit.hit(connection, ratelimit.address_key(request, settings, "test"), 2, 3600)
        return {"ok": "yes"}

    @app.post("/test/limited-then-failed")
    def limited_then_failed(connection: ConnectionDep, request: Request) -> None:
        ratelimit.hit(connection, ratelimit.address_key(request, settings, "test"), 2, 3600)
        raise ApiError(401, "not_signed_in")

    return app


@pytest.fixture
def extended(settings: Settings) -> Iterator[TestClient]:
    with TestClient(extended_app(settings), base_url=SITE, headers={"Origin": SITE}) as client:
        yield client


def test_a_first_upload_opens_one_session(extended: TestClient, conn: Connection) -> None:
    first = extended.post("/test/first-upload")
    owner = first.json()["owner"]
    cookie = first.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Max-Age=2592000" in cookie
    # The cookie is what identifies the visitor from then on: no second session.
    second = extended.post("/test/first-upload")
    assert second.json()["owner"] == owner
    assert "set-cookie" not in second.headers
    assert extended.get(ME).json()["kind"] == "anonymous"
    assert (
        count(conn, "SELECT count(*) FROM anonymous_sessions WHERE id = %s", uuid.UUID(owner)) == 1
    )


def test_cookies_are_bound_to_the_host_over_https(api_url: str) -> None:
    site = "https://example.test"
    settings = Settings(database_url=api_url, site_url=site, session_secret="s")
    with TestClient(extended_app(settings), base_url=site, headers={"Origin": site}) as client:
        cookie = client.post("/test/first-upload").headers["set-cookie"]
        assert cookie.startswith("__Host-anon=")
        assert "Secure" in cookie
        assert "Path=/" in cookie
        assert client.get(ME).json()["kind"] == "anonymous"


def test_an_error_rolls_the_transaction_back(extended: TestClient, conn: Connection) -> None:
    assert extended.post("/test/fail-after-write").status_code == 409
    assert count(conn, "SELECT count(*) FROM users WHERE display_name = 'rolled back'") == 0


def test_a_write_is_committed_before_the_response(extended: TestClient, conn: Connection) -> None:
    before = count(conn, "SELECT count(*) FROM users WHERE display_name = 'committed'")
    assert extended.post("/test/write").status_code == 200
    # Read at once, on another connection: nothing may still be pending.
    assert count(conn, "SELECT count(*) FROM users WHERE display_name = 'committed'") == before + 1


def test_owned_match_gives_the_owner_their_link(
    conn: Connection, make: Factory, api_url: str
) -> None:
    user, match = make.user(), make.match()
    make.user_match(match, user_id=user)
    with psycopg.connect(api_url) as api:
        link = owner_module.owned_match(api, Owner(user_id=user), match)
    assert link["match_id"] == match
    assert link["verified"] is False


def test_owned_match_hides_other_peoples_matches(make: Factory, api_url: str) -> None:
    match = make.match()
    session = make.anonymous_session()
    make.user_match(match, user_id=make.user())
    with psycopg.connect(api_url) as api:
        for stranger in (Owner(user_id=make.user()), Owner(anonymous_session_id=session)):
            with pytest.raises(ApiError) as error:
                owner_module.owned_match(api, stranger, match)
            assert (error.value.status, error.value.code) == (404, "not_found")


def test_a_missing_match_looks_the_same(make: Factory, api_url: str) -> None:
    with psycopg.connect(api_url) as api, pytest.raises(ApiError) as error:
        owner_module.owned_match(api, Owner(user_id=make.user()), uuid.uuid4())
    assert (error.value.status, error.value.code) == (404, "not_found")


def test_an_owner_is_one_or_the_other() -> None:
    with pytest.raises(ValueError, match="owner"):
        Owner()
    with pytest.raises(ValueError, match="owner"):
        Owner(user_id=uuid.uuid4(), anonymous_session_id=uuid.uuid4())


@pytest.mark.usefixtures("clean_limits")
def test_requests_past_the_limit_are_refused(extended: TestClient) -> None:
    assert extended.post("/test/limited").status_code == 200
    assert extended.post("/test/limited").status_code == 200
    refused = extended.post("/test/limited")
    assert refused.status_code == 429
    assert refused.json()["error"]["code"] == "rate_limited"
    assert 1 <= int(refused.headers["retry-after"]) <= 3600
    assert refused.json()["error"]["details"]["retry_after_s"] == int(
        refused.headers["retry-after"]
    )
    # A refused request stays refused.
    assert extended.post("/test/limited").status_code == 429


@pytest.mark.usefixtures("clean_limits")
def test_failed_attempts_count(extended: TestClient) -> None:
    """Their rollback must not take the count with it, or guessing would never be limited."""
    assert extended.post("/test/limited-then-failed").status_code == 401
    assert extended.post("/test/limited-then-failed").status_code == 401
    assert extended.post("/test/limited-then-failed").status_code == 429


@pytest.mark.usefixtures("clean_limits")
def test_a_spoofed_address_does_not_dodge_the_limit(extended: TestClient) -> None:
    """One trusted proxy: it appends the real address, so only the last entry counts."""
    for index in range(2):
        response = extended.post(
            "/test/limited", headers={"X-Forwarded-For": f"10.0.0.{index}, 203.0.113.7"}
        )
        assert response.status_code == 200
    refused = extended.post("/test/limited", headers={"X-Forwarded-For": "10.0.0.99, 203.0.113.7"})
    assert refused.status_code == 429


@pytest.mark.usefixtures("clean_limits")
def test_addresses_are_counted_apart_and_never_in_clear(
    extended: TestClient, conn: Connection
) -> None:
    for address in ("203.0.113.1", "203.0.113.2"):
        for _ in range(2):
            response = extended.post("/test/limited", headers={"X-Forwarded-For": address})
            assert response.status_code == 200
    rows = conn.execute("SELECT bucket_key FROM rate_limit_buckets").fetchall()
    assert len(rows) == 2
    assert not any("203.0.113" in row[0] for row in rows)
