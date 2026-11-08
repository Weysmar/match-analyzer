"""The purge (step 9, T9.8), against PostgreSQL with the worker's own role. The clock is moved,
never waited for: every step takes `now`."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from ma_db.testing import Connection, Factory, count
from ma_worker import purge
from ma_worker.settings import Settings

from .helpers import MemoryStore

pytestmark = pytest.mark.db

SETTINGS = Settings(database_url="unused")
NOW = datetime.now(UTC)


def parsed_match(
    conn: Connection, make: Factory, store: MemoryStore, status: str, days_ago: float
) -> uuid.UUID:
    match = make.match(status)
    key = f"raw/{match.hex}.replay"
    conn.execute(
        "UPDATE matches SET raw_key = %s, parsed_at = %s WHERE id = %s",
        (key, NOW - timedelta(days=days_ago), match),
    )
    store.objects[key] = b"replay"
    return match


def raw_deleted(conn: Connection, match: uuid.UUID) -> bool:
    row = conn.execute("SELECT raw_deleted_at FROM matches WHERE id = %s", (match,)).fetchone()
    assert row is not None
    return row[0] is not None


@pytest.mark.parametrize(
    ("status", "days_ago", "purged"),
    [
        ("ready", 31, True),
        ("ready", 29, False),
        ("parsed", 31, True),
        ("analyzing", 31, True),
        ("header_only", 31, False),
        ("header_only", 181, True),
        ("failed", 31, False),
        ("failed", 181, True),
        ("pending", 400, False),
        ("parsing", 400, False),
    ],
)
def test_raw_files_go_after_their_retention(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    status: str,
    days_ago: float,
    purged: bool,
) -> None:
    store = MemoryStore()
    match = parsed_match(conn, make, store, status, days_ago)
    assert purge.raw_files(worker_conn, store, SETTINGS, NOW) == int(purged)
    assert raw_deleted(conn, match) is purged
    assert (f"raw/{match.hex}.replay" in store.objects) is not purged


def test_a_raw_file_is_purged_once(
    conn: Connection, worker_conn: Connection, make: Factory
) -> None:
    store = MemoryStore()
    parsed_match(conn, make, store, "ready", 31)
    assert purge.raw_files(worker_conn, store, SETTINGS, NOW) == 1
    assert purge.raw_files(worker_conn, store, SETTINGS, NOW) == 0


def test_retention_comes_from_the_settings(
    conn: Connection, worker_conn: Connection, make: Factory
) -> None:
    store = MemoryStore()
    match = parsed_match(conn, make, store, "ready", 8)
    week = Settings(database_url="unused", raw_retention_days=7)
    assert purge.raw_files(worker_conn, store, week, NOW) == 1
    assert raw_deleted(conn, match)


def test_a_store_that_fails_leaves_the_file_marked_as_kept(
    conn: Connection, worker_conn: Connection, make: Factory
) -> None:
    store = MemoryStore()
    match = parsed_match(conn, make, store, "ready", 31)
    store.broken.add("delete")
    report = purge.run(worker_conn, store, SETTINGS, NOW)
    assert report.raw_files == 0
    assert not raw_deleted(conn, match)


def test_files_never_sent_go_after_a_day(
    conn: Connection, worker_conn: Connection, make: Factory
) -> None:
    store = MemoryStore()
    session = make.anonymous_session()
    old, recent, sent = (make.upload(anonymous_session_id=session) for _ in range(3))
    conn.execute(
        "UPDATE uploads SET created_at = %s WHERE id = ANY(%s)",
        (NOW - timedelta(days=2), [old, sent]),
    )
    conn.execute("UPDATE uploads SET status = 'uploaded' WHERE id = %s", (sent,))
    for upload in (old, recent, sent):
        store.objects[f"incoming/{upload}"] = b"part"
    assert purge.stale_uploads(worker_conn, store, NOW) == 1
    assert count(conn, "SELECT count(*) FROM uploads WHERE id = %s", old) == 0
    assert f"incoming/{old}" not in store.objects
    assert {f"incoming/{recent}", f"incoming/{sent}"} <= set(store.objects)


def test_an_expired_session_lets_its_matches_go(
    conn: Connection, worker_conn: Connection, make: Factory
) -> None:
    session = make.anonymous_session()
    kept = make.anonymous_session()
    alone, shared = make.match(), make.match()
    make.user_match(alone, anonymous_session_id=session)
    make.user_match(shared, anonymous_session_id=session)
    make.user_match(shared, user_id=make.user())
    make.upload(anonymous_session_id=session, match_id=alone)
    conn.execute(
        "UPDATE anonymous_sessions SET expires_at = %s WHERE id = %s",
        (NOW - timedelta(minutes=1), session),
    )
    sessions, queued = purge.anonymous_sessions(worker_conn, NOW)
    assert (sessions, queued) == (1, 2)
    assert count(conn, "SELECT count(*) FROM anonymous_sessions WHERE id = %s", session) == 0
    assert count(conn, "SELECT count(*) FROM anonymous_sessions WHERE id = %s", kept) == 1
    assert count(conn, "SELECT count(*) FROM uploads WHERE anonymous_session_id = %s", session) == 0
    jobs = conn.execute(
        "SELECT payload->>'match_id' FROM jobs WHERE kind = 'gc_match' ORDER BY 1"
    ).fetchall()
    # Both are queued; `gc_match` keeps the one another player still holds.
    assert sorted(row[0] for row in jobs) == sorted([str(alone), str(shared)])


def test_expired_account_sessions_and_old_counters_go(
    conn: Connection, worker_conn: Connection, make: Factory
) -> None:
    user = make.user()
    for expires in (NOW - timedelta(hours=1), NOW + timedelta(days=1)):
        conn.execute(
            "INSERT INTO auth_sessions (user_id, token_hash, expires_at) VALUES (%s, %s, %s)",
            (user, uuid.uuid4().bytes, expires),
        )
    conn.execute("DELETE FROM rate_limit_buckets")
    for age in (timedelta(days=3), timedelta(hours=1)):
        conn.execute(
            "INSERT INTO rate_limit_buckets (bucket_key, window_start, hits) VALUES ('k', %s, 1)",
            (NOW - age,),
        )
    assert purge.auth_sessions(worker_conn, NOW) == 1
    assert purge.counters(worker_conn, NOW) == 1
    assert count(conn, "SELECT count(*) FROM auth_sessions WHERE user_id = %s", user) == 1
    assert count(conn, "SELECT count(*) FROM rate_limit_buckets") == 1


def test_a_full_pass_reports_what_it_did(
    conn: Connection, worker_conn: Connection, make: Factory
) -> None:
    store = MemoryStore()
    parsed_match(conn, make, store, "ready", 31)
    report = purge.run(worker_conn, store, SETTINGS, NOW + timedelta(days=60))
    assert report.raw_files == 1
    assert "raw files 1" in str(report)
