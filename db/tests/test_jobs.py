"""The claim pattern the worker will use: two workers never take the same job."""

import json
from collections.abc import Iterator

import psycopg
import pytest

from ma_db.testing import Connection

pytestmark = pytest.mark.db

CLAIM = b"""
    SELECT id FROM jobs
    WHERE status = 'queued' AND run_at <= now()
    ORDER BY priority DESC, run_at
    LIMIT 1
    FOR UPDATE SKIP LOCKED
"""


def claim(connection: Connection) -> int | None:
    row = connection.execute(CLAIM).fetchone()
    return None if row is None else int(row[0])


@pytest.fixture
def jobs(database: str) -> Iterator[list[int]]:
    """Three committed jobs: the claims have to see them from other connections."""
    with psycopg.connect(database, autocommit=True) as connection:
        rows = connection.execute(
            "INSERT INTO jobs (kind, payload, priority) "
            "SELECT 'parse', %s, 0 FROM generate_series(1, 3) RETURNING id",
            (json.dumps({"upload_id": "x"}),),
        ).fetchall()
        ids = [int(row[0]) for row in rows]
        try:
            yield ids
        finally:
            connection.execute("DELETE FROM jobs WHERE id = ANY(%s)", (ids,))


def test_two_workers_take_different_jobs(database: str, jobs: list[int]) -> None:
    with psycopg.connect(database) as first, psycopg.connect(database) as second:
        taken = [claim(first), claim(second)]
        assert None not in taken
        assert len(set(taken)) == 2
        assert set(taken) <= set(jobs)
        first.rollback()
        second.rollback()


def test_a_worker_finds_nothing_when_all_jobs_are_taken(database: str, jobs: list[int]) -> None:
    with psycopg.connect(database) as holder, psycopg.connect(database) as other:
        held = holder.execute(
            b"SELECT id FROM jobs WHERE status = 'queued' FOR UPDATE SKIP LOCKED"
        ).fetchall()
        assert len(held) == len(jobs)
        assert claim(other) is None
        holder.rollback()
        other.rollback()


def test_a_job_is_free_again_after_a_crash(database: str, jobs: list[int]) -> None:
    with psycopg.connect(database) as crashed:
        taken = claim(crashed)
        crashed.rollback()
    with psycopg.connect(database) as other:
        assert claim(other) == taken
        other.rollback()


def test_priority_comes_first(conn: Connection) -> None:
    conn.execute("UPDATE jobs SET status = 'done'")
    conn.execute("INSERT INTO jobs (kind, priority) VALUES ('parse', 0)")
    row = conn.execute("INSERT INTO jobs (kind, priority) VALUES ('parse', 5) RETURNING id")
    urgent = row.fetchone()
    assert urgent is not None
    assert claim(conn) == urgent[0]


def test_a_job_scheduled_for_later_waits(conn: Connection) -> None:
    conn.execute("UPDATE jobs SET status = 'done'")
    conn.execute("INSERT INTO jobs (kind, run_at) VALUES ('parse', now() + interval '1 hour')")
    assert claim(conn) is None
