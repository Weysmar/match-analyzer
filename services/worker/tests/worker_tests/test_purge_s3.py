"""The purge and `gc_match` against the real object store and database (T9.8: objects deleted on
S3). Needs `just dev-up`; run by `just test-s3` and the CI's stack job."""

import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ma_db.testing import Connection, Factory, count
from ma_worker import erase, purge
from ma_worker.queue import Job
from ma_worker.settings import Settings
from ma_worker.store import S3Store

pytestmark = [pytest.mark.s3, pytest.mark.db]


@pytest.fixture
def store() -> S3Store:
    endpoint = os.environ.get("S3_ENDPOINT")
    if not endpoint:
        pytest.skip("S3_ENDPOINT is not set: run `just dev-up`, then `just test-s3`")
    return S3Store(
        Settings(
            database_url="unused",
            s3_endpoint=endpoint,
            s3_region=os.environ.get("S3_REGION", "us-east-1"),
            s3_bucket=os.environ["S3_BUCKET"],
            s3_access_key_id=os.environ["S3_ACCESS_KEY_ID"],
            s3_secret_access_key=os.environ["S3_SECRET_ACCESS_KEY"],
        )
    )


def put(store: S3Store, key: str, tmp_path: Path) -> None:
    source = tmp_path / uuid.uuid4().hex
    source.write_bytes(b"replay bytes")
    store.upload(source, key, "application/octet-stream")
    assert store.size(key) is not None


def test_an_old_raw_file_leaves_the_store(
    conn: Connection, worker_conn: Connection, make: Factory, store: S3Store, tmp_path: Path
) -> None:
    match = make.match("ready")
    key = f"test-worker/raw/{match}.replay"
    put(store, key, tmp_path)
    now = datetime.now(UTC)
    conn.execute(
        "UPDATE matches SET raw_key = %s, parsed_at = %s WHERE id = %s",
        (key, now - timedelta(days=31), match),
    )
    report = purge.run(worker_conn, store, Settings(database_url="unused"), now)
    assert report.raw_files == 1
    assert store.size(key) is None


def test_an_erased_match_leaves_no_file(
    conn: Connection, worker_conn: Connection, make: Factory, store: S3Store, tmp_path: Path
) -> None:
    match = make.match("ready")
    keys = [f"test-worker/{kind}/{match}" for kind in ("raw", "frames", "events")]
    for key in keys:
        put(store, key, tmp_path)
    conn.execute(
        "UPDATE matches SET raw_key = %s, frames_key = %s, events_key = %s WHERE id = %s",
        (*keys, match),
    )
    erase.handle(worker_conn, Job(1, "gc_match", {"match_id": str(match)}, 1, 3), store)
    assert count(conn, "SELECT count(*) FROM matches WHERE id = %s", match) == 0
    assert [store.size(key) for key in keys] == [None, None, None]
