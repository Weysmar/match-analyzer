"""A real PUT on the object store, from a URL the API signed. Needs `just dev-up`."""

import http.client
import os
import urllib.parse
from collections.abc import Iterator
from dataclasses import replace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ma_api.settings import PREFIX, Settings
from ma_db.testing import Connection

from .helpers import FakeProviders, browser_for

pytestmark = [pytest.mark.s3, pytest.mark.usefixtures("clean_limits")]

UPLOADS = f"{PREFIX}/uploads"
BODY = b"not a replay, and the API does not care" * 10


@pytest.fixture
def real(settings: Settings, providers: FakeProviders) -> Iterator[TestClient]:
    endpoint = os.environ.get("S3_ENDPOINT")
    if not endpoint:
        pytest.skip("S3_ENDPOINT is not set: run `just dev-up`, then `just test-s3`")
    configured = replace(
        settings,
        s3_endpoint=endpoint,
        s3_public_endpoint=os.environ.get("S3_PUBLIC_ENDPOINT", ""),
        s3_region=os.environ.get("S3_REGION", "us-east-1"),
        s3_bucket=os.environ["S3_BUCKET"],
        s3_access_key_id=os.environ["S3_ACCESS_KEY_ID"],
        s3_secret_access_key=os.environ["S3_SECRET_ACCESS_KEY"],
    )
    # No store given: the application builds its real one.
    with browser_for(configured, providers, store=None) as client:
        yield client


def put(url: str, headers: dict[str, str], body: bytes) -> int:
    """Sends the request as written, the way a browser would."""
    parts = urllib.parse.urlsplit(url)
    connection = http.client.HTTPConnection(parts.netloc, timeout=15)
    try:
        connection.request("PUT", f"{parts.path}?{parts.query}", body=body, headers=headers)
        return connection.getresponse().status
    finally:
        connection.close()


def open_upload(client: TestClient, size: int) -> dict[str, Any]:
    response = client.post(UPLOADS, json={"files": [{"name": "a.replay", "size": size}]})
    assert response.status_code == 201
    created: dict[str, Any] = response.json()["uploads"][0]
    return created


def test_a_file_goes_from_the_browser_to_the_queue(real: TestClient, conn: Connection) -> None:
    created = open_upload(real, len(BODY))
    upload_id = created["upload_id"]
    missing = real.post(f"{UPLOADS}/{upload_id}/complete")
    assert missing.status_code == 422
    assert missing.json()["error"]["code"] == "object_missing"

    assert put(created["url"], created["headers"], BODY) == 200
    response = real.post(f"{UPLOADS}/{upload_id}/complete")
    assert response.status_code == 202
    jobs = conn.execute(
        "SELECT kind FROM jobs WHERE payload->>'upload_id' = %s", (upload_id,)
    ).fetchall()
    assert jobs == [("parse",)]


def test_the_store_refuses_a_body_of_another_size(real: TestClient) -> None:
    for sent in (BODY + b"more", BODY[:-1]):
        created = open_upload(real, len(BODY))
        assert put(created["url"], created["headers"], sent) not in (200, 201)
        # Nothing arrived: the API says so.
        response = real.post(f"{UPLOADS}/{created['upload_id']}/complete")
        assert response.json()["error"]["code"] == "object_missing"


def test_the_store_refuses_another_content_type(real: TestClient) -> None:
    created = open_upload(real, len(BODY))
    assert put(created["url"], {"Content-Type": "text/html"}, BODY) not in (200, 201)
