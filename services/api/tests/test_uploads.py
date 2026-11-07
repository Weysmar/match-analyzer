"""Uploads, with a simulated object store, against PostgreSQL with the API's own role."""

import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from typing import Any

import httpx2
import pytest
from fastapi.testclient import TestClient

from ma_api.settings import PREFIX, Settings
from ma_api.storage import CONTENT_TYPE
from ma_db.testing import Connection, Factory, count

from .helpers import (
    ME,
    STEAM_IDS,
    FakeProviders,
    FakeStore,
    anonymous_session,
    browser_for,
    steam_sign_in,
    user_session,
)

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_limits")]

UPLOADS = f"{PREFIX}/uploads"
HASH = "a" * 64
OTHER_HASH = "b" * 64


@pytest.fixture
def store() -> FakeStore:
    return FakeStore()


@pytest.fixture
def uploader(
    settings: Settings, providers: FakeProviders, store: FakeStore
) -> Iterator[TestClient]:
    with browser_for(settings, providers, store) as client:
        yield client


def one(name: str = "a.replay", size: int = 100, **fields: Any) -> dict[str, Any]:
    return {"name": name, "size": size, **fields}


def post(client: TestClient, *files: dict[str, Any]) -> httpx2.Response:
    return client.post(UPLOADS, json={"files": list(files)})


def open_upload(client: TestClient, size: int = 100) -> str:
    response = post(client, one(size=size))
    assert response.status_code == 201
    upload_id: str = response.json()["uploads"][0]["upload_id"]
    return upload_id


def complete(client: TestClient, upload_id: str) -> httpx2.Response:
    return client.post(f"{UPLOADS}/{upload_id}/complete")


def uploads_count(conn: Connection) -> int:
    return count(conn, "SELECT count(*) FROM uploads")


def jobs_of(conn: Connection, upload_id: str) -> list[tuple[Any, ...]]:
    return conn.execute(
        "SELECT kind, status FROM jobs WHERE payload->>'upload_id' = %s", (upload_id,)
    ).fetchall()


def test_a_first_upload_opens_a_session(
    uploader: TestClient, conn: Connection, store: FakeStore
) -> None:
    response = post(uploader, one("mine.replay", 1234, sha256=HASH))
    assert response.status_code == 201
    assert "HttpOnly" in response.headers["set-cookie"]
    assert uploader.get(ME).json()["kind"] == "anonymous"
    created = response.json()["uploads"][0]
    assert created["status"] == "awaiting_file"
    assert created["method"] == "PUT"
    assert created["headers"] == {"Content-Type": CONTENT_TYPE}
    assert created["expires_at"]
    key = f"incoming/{created['upload_id']}"
    assert created["url"] == f"https://store.test/{key}?size=1234"
    row = conn.execute(
        "SELECT file_name, declared_size, declared_sha256, sha256, status, incoming_key, "
        "user_id, anonymous_session_id IS NOT NULL FROM uploads WHERE id = %s",
        (created["upload_id"],),
    ).fetchone()
    # The browser's hash is kept apart: only the worker fills the real one.
    assert row == ("mine.replay", 1234, HASH, None, "awaiting_file", key, None, True)


def test_a_signed_in_user_owns_their_uploads(uploader: TestClient, conn: Connection) -> None:
    steam_sign_in(uploader, next(STEAM_IDS))
    user = uploader.get(ME).json()["user"]["id"]
    upload_id = open_upload(uploader)
    assert (
        count(conn, "SELECT count(*) FROM uploads WHERE id = %s AND user_id = %s", upload_id, user)
        == 1
    )
    assert uploader.get(ME).json()["kind"] == "user"


def test_several_files_stay_in_order(uploader: TestClient) -> None:
    names = [f"{index}.replay" for index in range(3)]
    created = post(uploader, *[one(name) for name in names]).json()["uploads"]
    assert len({item["upload_id"] for item in created}) == 3
    listed = {item["upload_id"]: item["name"] for item in uploader.get(UPLOADS).json()["items"]}
    assert [listed[item["upload_id"]] for item in created] == names


def test_a_batch_at_the_limit_goes_through(settings: Settings, providers: FakeProviders) -> None:
    limited = replace(settings, upload_max_files=2, upload_max_bytes=100)
    with browser_for(limited, providers, FakeStore()) as client:
        assert post(client, one(size=100), one(size=1)).status_code == 201


def test_too_many_files_are_refused(
    settings: Settings, providers: FakeProviders, conn: Connection
) -> None:
    before = uploads_count(conn)
    limited = replace(settings, upload_max_files=2)
    with browser_for(limited, providers, FakeStore()) as client:
        response = post(client, one(), one(), one())
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "too_many_files"
    assert response.json()["error"]["details"] == {"max_files": 2}
    assert "set-cookie" not in response.headers
    assert uploads_count(conn) == before


def test_a_file_too_large_refuses_the_batch(
    settings: Settings, providers: FakeProviders, conn: Connection
) -> None:
    before = uploads_count(conn)
    limited = replace(settings, upload_max_bytes=100)
    with browser_for(limited, providers, FakeStore()) as client:
        response = post(client, one(size=100), one(size=101))
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "too_large"
    assert "set-cookie" not in response.headers
    assert uploads_count(conn) == before


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"files": []},
        {"files": [{"name": "a.replay"}]},
        {"files": [{"name": "", "size": 1}]},
        {"files": [{"name": "x" * 256, "size": 1}]},
        {"files": [{"name": "a\nb", "size": 1}]},
        {"files": [{"name": "a.replay", "size": 0}]},
        {"files": [{"name": "a.replay", "size": -1}]},
        {"files": [{"name": "a.replay", "size": 1, "sha256": "short"}]},
        {"files": [{"name": "a.replay", "size": 1, "sha256": "A" * 64}]},
    ],
)
def test_invalid_input_is_refused(
    uploader: TestClient, conn: Connection, body: dict[str, Any]
) -> None:
    before = uploads_count(conn)
    response = uploader.post(UPLOADS, json=body)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"
    assert uploads_count(conn) == before


def test_another_site_cannot_upload(uploader: TestClient) -> None:
    response = uploader.post(
        UPLOADS, json={"files": [one()]}, headers={"Origin": "https://evil.test"}
    )
    assert response.status_code == 403


def test_a_file_i_already_brought_is_a_duplicate(
    uploader: TestClient, conn: Connection, make: Factory
) -> None:
    upload_id = open_upload(uploader)
    match = make.match()
    conn.execute(
        "UPDATE uploads SET sha256 = %s, match_id = %s WHERE id = %s", (HASH, match, upload_id)
    )
    before = uploads_count(conn)
    response = post(uploader, one(sha256=HASH), one(sha256=OTHER_HASH))
    assert response.status_code == 201
    duplicate, fresh = response.json()["uploads"]
    assert duplicate == {"upload_id": upload_id, "status": "duplicate", "match_id": str(match)}
    assert fresh["status"] == "awaiting_file"
    assert uploads_count(conn) == before + 1


def test_a_hash_someone_else_brought_gives_nothing(
    uploader: TestClient, conn: Connection, make: Factory
) -> None:
    """Knowing a hash must not be enough to obtain a match."""
    match = make.match()
    theirs = make.upload(user_id=make.user(), match_id=match)
    conn.execute("UPDATE uploads SET sha256 = %s WHERE id = %s", (HASH, theirs))
    created = post(uploader, one(sha256=HASH)).json()["uploads"][0]
    assert created["status"] == "awaiting_file"
    assert str(match) not in json.dumps(created)


def test_a_hash_only_declared_proves_nothing(uploader: TestClient, conn: Connection) -> None:
    upload_id = open_upload(uploader)
    conn.execute("UPDATE uploads SET declared_sha256 = %s WHERE id = %s", (HASH, upload_id))
    assert post(uploader, one(sha256=HASH)).json()["uploads"][0]["status"] == "awaiting_file"


@contextmanager
def quota_client(
    settings: Settings, providers: FakeProviders, **limits: int
) -> Iterator[TestClient]:
    with browser_for(replace(settings, **limits), providers, FakeStore()) as client:  # type: ignore[arg-type]
        yield client


def test_an_anonymous_session_has_a_quota(settings: Settings, providers: FakeProviders) -> None:
    with quota_client(settings, providers, rate_upload_anon_per_day=2) as client:
        assert post(client, one(), one()).status_code == 201
        refused = post(client, one())
    assert refused.status_code == 429
    assert refused.json()["error"]["code"] == "quota_exceeded"
    retry = int(refused.headers["retry-after"])
    assert 1 <= retry <= 86_400
    assert refused.json()["error"]["details"]["retry_after_s"] == retry


def test_a_new_session_does_not_escape_the_address_quota(
    settings: Settings, providers: FakeProviders
) -> None:
    with quota_client(settings, providers, rate_upload_ip_per_day=2) as client:
        assert post(client, one(), one()).status_code == 201
        client.cookies.clear()
        assert post(client, one()).status_code == 429


def test_another_address_has_its_own_quota(settings: Settings, providers: FakeProviders) -> None:
    with quota_client(settings, providers, rate_upload_ip_per_day=1) as client:
        headers = {"X-Forwarded-For": "203.0.113.1"}
        assert client.post(UPLOADS, json={"files": [one()]}, headers=headers).status_code == 201
        client.cookies.clear()
        headers = {"X-Forwarded-For": "203.0.113.2"}
        assert client.post(UPLOADS, json={"files": [one()]}, headers=headers).status_code == 201


def test_a_user_has_a_quota(
    settings: Settings, providers: FakeProviders, conn: Connection, make: Factory
) -> None:
    with quota_client(settings, providers, rate_upload_user_per_day=1) as client:
        client.cookies.set("session", user_session(conn, make.user()))
        assert post(client, one()).status_code == 201
        assert post(client, one()).status_code == 429


def test_a_refused_batch_costs_nothing(
    settings: Settings, providers: FakeProviders, conn: Connection
) -> None:
    with quota_client(settings, providers, rate_upload_anon_per_day=3) as client:
        assert post(client, one(), one()).status_code == 201
        before = uploads_count(conn)
        assert post(client, one(), one()).status_code == 429
        assert uploads_count(conn) == before
        # What is left can still be used.
        assert post(client, one()).status_code == 201


def test_a_refused_first_batch_opens_no_session(
    settings: Settings, providers: FakeProviders, conn: Connection
) -> None:
    before = count(conn, "SELECT count(*) FROM anonymous_sessions")
    with quota_client(settings, providers, rate_upload_ip_per_day=1) as client:
        refused = post(client, one(), one())
    assert refused.status_code == 429
    assert "set-cookie" not in refused.headers
    assert count(conn, "SELECT count(*) FROM anonymous_sessions") == before


def test_a_duplicate_uses_no_quota(
    settings: Settings, providers: FakeProviders, conn: Connection, make: Factory
) -> None:
    with quota_client(settings, providers, rate_upload_anon_per_day=1) as client:
        upload_id = open_upload(client)
        conn.execute(
            "UPDATE uploads SET sha256 = %s, match_id = %s WHERE id = %s",
            (HASH, make.match(), upload_id),
        )
        response = post(client, one(sha256=HASH))
    assert response.status_code == 201
    assert response.json()["uploads"][0]["status"] == "duplicate"


def test_counters_hold_no_address_in_clear(uploader: TestClient, conn: Connection) -> None:
    uploader.post(UPLOADS, json={"files": [one()]}, headers={"X-Forwarded-For": "203.0.113.9"})
    rows = conn.execute("SELECT bucket_key FROM rate_limit_buckets").fetchall()
    assert rows
    assert not any("203.0.113" in row[0] for row in rows)


def test_complete_queues_the_file(uploader: TestClient, conn: Connection, store: FakeStore) -> None:
    upload_id = open_upload(uploader, size=100)
    store.sizes[f"incoming/{upload_id}"] = 100
    response = complete(uploader, upload_id)
    assert response.status_code == 202
    assert response.json() == {"upload_id": upload_id, "status": "uploaded"}
    row = conn.execute(
        "SELECT status, completed_at IS NOT NULL FROM uploads WHERE id = %s", (upload_id,)
    ).fetchone()
    assert row == ("uploaded", True)
    assert jobs_of(conn, upload_id) == [("parse", "queued")]


def test_complete_without_the_file_can_be_retried(
    uploader: TestClient, conn: Connection, store: FakeStore
) -> None:
    upload_id = open_upload(uploader)
    response = complete(uploader, upload_id)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "object_missing"
    assert jobs_of(conn, upload_id) == []
    store.sizes[f"incoming/{upload_id}"] = 100
    assert complete(uploader, upload_id).status_code == 202


def test_complete_with_the_wrong_size_rejects_the_file(
    uploader: TestClient, conn: Connection, store: FakeStore
) -> None:
    upload_id = open_upload(uploader, size=100)
    store.sizes[f"incoming/{upload_id}"] = 101
    response = complete(uploader, upload_id)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "size_mismatch"
    assert jobs_of(conn, upload_id) == []
    item = uploader.get(f"{UPLOADS}/{upload_id}").json()
    assert (item["status"], item["rejection"]) == ("rejected", "size_mismatch")
    # It cannot be completed afterwards.
    store.sizes[f"incoming/{upload_id}"] = 100
    assert complete(uploader, upload_id).status_code == 409


def test_completing_twice_queues_once(
    uploader: TestClient, conn: Connection, store: FakeStore
) -> None:
    upload_id = open_upload(uploader)
    store.sizes[f"incoming/{upload_id}"] = 100
    assert complete(uploader, upload_id).status_code == 202
    again = complete(uploader, upload_id)
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "invalid_state"
    assert again.json()["error"]["details"] == {"status": "uploaded"}
    assert jobs_of(conn, upload_id) == [("parse", "queued")]


def test_a_store_that_is_down_changes_nothing(
    uploader: TestClient, conn: Connection, store: FakeStore
) -> None:
    upload_id = open_upload(uploader)
    store.down = True
    response = complete(uploader, upload_id)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "unavailable"
    assert jobs_of(conn, upload_id) == []
    assert uploader.get(f"{UPLOADS}/{upload_id}").json()["status"] == "awaiting_file"


def test_someone_elses_upload_does_not_exist_for_me(
    uploader: TestClient,
    settings: Settings,
    providers: FakeProviders,
    store: FakeStore,
    conn: Connection,
) -> None:
    upload_id = open_upload(uploader)
    store.sizes[f"incoming/{upload_id}"] = 100
    with browser_for(settings, providers, store) as stranger:
        open_upload(stranger)
        assert complete(stranger, upload_id).status_code == 404
        assert stranger.get(f"{UPLOADS}/{upload_id}").status_code == 404
        assert upload_id not in stranger.get(UPLOADS).text
    assert jobs_of(conn, upload_id) == []


def test_an_upload_unknown_to_anybody_looks_the_same(uploader: TestClient) -> None:
    open_upload(uploader)
    missing = uuid.uuid4()
    assert complete(uploader, str(missing)).status_code == 404
    assert uploader.get(f"{UPLOADS}/{missing}").status_code == 404


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_a_bad_id_is_invalid(uploader: TestClient, method: str) -> None:
    path = f"{UPLOADS}/not-an-id" + ("/complete" if method == "POST" else "")
    assert uploader.request(method, path).status_code == 400


def test_nobody_has_no_uploads(uploader: TestClient) -> None:
    for response in (
        uploader.get(UPLOADS),
        uploader.get(f"{UPLOADS}/{uuid.uuid4()}"),
        complete(uploader, str(uuid.uuid4())),
    ):
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "not_signed_in"


def test_the_list_shows_each_uploads_state(
    uploader: TestClient, conn: Connection, make: Factory
) -> None:
    upload_id = open_upload(uploader)
    match = make.match()
    conn.execute(
        "UPDATE uploads SET status = 'done', match_id = %s WHERE id = %s", (match, upload_id)
    )
    body = uploader.get(UPLOADS).json()
    assert body == {
        "items": [
            {
                "upload_id": upload_id,
                "name": "a.replay",
                "status": "done",
                "rejection": None,
                "match_id": str(match),
            }
        ],
        "next_cursor": None,
    }
    assert uploader.get(f"{UPLOADS}/{upload_id}").json() == body["items"][0]


def test_the_list_filters_by_status(uploader: TestClient, conn: Connection) -> None:
    kept, other = open_upload(uploader), open_upload(uploader)
    conn.execute("UPDATE uploads SET status = 'done' WHERE id = %s", (other,))
    items = uploader.get(UPLOADS, params={"status": "awaiting_file"}).json()["items"]
    assert [item["upload_id"] for item in items] == [kept]
    assert uploader.get(UPLOADS, params={"status": "nonsense"}).status_code == 400


def test_the_list_goes_page_by_page(uploader: TestClient) -> None:
    created = post(uploader, *[one(f"{index}.replay") for index in range(5)]).json()["uploads"]
    open_upload(uploader)
    seen: list[str] = []
    params: dict[str, Any] = {"limit": 2}
    pages = 0
    while True:
        body = uploader.get(UPLOADS, params=params).json()
        seen += [item["upload_id"] for item in body["items"]]
        pages += 1
        if body["next_cursor"] is None:
            break
        params["cursor"] = body["next_cursor"]
    assert pages == 3
    assert len(seen) == len(set(seen)) == 6
    assert {item["upload_id"] for item in created} <= set(seen)


def test_a_page_exactly_full_has_no_next(uploader: TestClient) -> None:
    open_upload(uploader)
    assert uploader.get(UPLOADS, params={"limit": 1}).json()["next_cursor"] is None


@pytest.mark.parametrize(
    "params", [{"limit": 0}, {"limit": 201}, {"limit": "many"}, {"cursor": "nonsense"}]
)
def test_bad_list_parameters_are_invalid(uploader: TestClient, params: dict[str, Any]) -> None:
    open_upload(uploader)
    response = uploader.get(UPLOADS, params=params)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


def test_a_cursor_does_not_open_someone_elses_list(
    uploader: TestClient, settings: Settings, providers: FakeProviders, store: FakeStore
) -> None:
    post(uploader, one(), one())
    cursor = uploader.get(UPLOADS, params={"limit": 1}).json()["next_cursor"]
    with browser_for(settings, providers, store) as stranger:
        open_upload(stranger)
        items = stranger.get(UPLOADS, params={"cursor": cursor}).json()["items"]
    assert items == []


def test_uploads_follow_the_owner_at_sign_in(
    uploader: TestClient, conn: Connection, store: FakeStore
) -> None:
    upload_id = open_upload(uploader)
    steam_sign_in(uploader, next(STEAM_IDS))
    assert uploader.get(ME).json()["kind"] == "user"
    store.sizes[f"incoming/{upload_id}"] = 100
    assert complete(uploader, upload_id).status_code == 202
    assert [item["upload_id"] for item in uploader.get(UPLOADS).json()["items"]] == [upload_id]


def test_an_expired_session_has_no_uploads(
    settings: Settings, providers: FakeProviders, store: FakeStore, conn: Connection, make: Factory
) -> None:
    session, token = anonymous_session(conn, valid=False)
    upload = make.upload(anonymous_session_id=session)
    with browser_for(settings, providers, store) as client:
        client.cookies.set("anon", token)
        assert client.get(f"{UPLOADS}/{upload}").status_code == 401
