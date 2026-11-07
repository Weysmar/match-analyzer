"""The job queue: a PostgreSQL table, no broker in V1.

A job is claimed in one committed statement and then runs outside any transaction, so that a long
job holds no lock. A worker that dies leaves its job `running`: `recover` hands it back once it is
too old. Every write is conditional on still holding the job, so that a worker that was only slow
cannot overwrite what another one did since.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import psycopg

type Connection = psycopg.Connection[tuple[Any, ...]]

_BACKOFF_BASE_S = 30
_BACKOFF_FACTOR = 4
_BACKOFF_MAX_S = 3600


@dataclass(frozen=True)
class Job:
    id: int
    kind: str
    payload: dict[str, Any]
    attempts: int
    max_attempts: int


def backoff_s(attempts: int) -> int:
    """How long to wait after the attempt number `attempts`: 30 s, 2 min, 8 min..."""
    delay: int = _BACKOFF_BASE_S * _BACKOFF_FACTOR ** max(attempts - 1, 0)
    return min(delay, _BACKOFF_MAX_S)


def claim(connection: Connection, worker: str, kinds: Sequence[str]) -> Job | None:
    """The next job of these kinds, now this worker's. Two workers never get the same one."""
    row = connection.execute(
        """
        UPDATE jobs
        SET status = 'running', locked_by = %s, locked_at = now(), attempts = attempts + 1
        WHERE id = (
            SELECT id FROM jobs
            WHERE status = 'queued' AND run_at <= now() AND kind = ANY(%s)
            ORDER BY priority DESC, run_at
            LIMIT 1
            FOR UPDATE SKIP LOCKED
        )
        RETURNING id, kind, payload, attempts, max_attempts
        """,
        (worker, list(kinds)),
    ).fetchone()
    return None if row is None else Job(row[0], row[1], row[2], row[3], row[4])


def finish(connection: Connection, job: Job, worker: str) -> bool:
    """False when the job was no longer this worker's."""
    cursor = connection.execute(
        """
        UPDATE jobs
        SET status = 'done', finished_at = now(), locked_by = NULL, locked_at = NULL,
            last_error = NULL
        WHERE id = %s AND status = 'running' AND locked_by = %s
        """,
        (job.id, worker),
    )
    return cursor.rowcount == 1


def fail(connection: Connection, job: Job, worker: str, code: str, *, retry: bool = True) -> bool:
    """Puts the job back for later, or marks it dead when it should not or cannot try again.

    `code` names the failure and nothing more: the text of an exception can quote a player's name,
    and this column is read by whoever looks after the queue.
    """
    if retry and job.attempts < job.max_attempts:
        cursor = connection.execute(
            """
            UPDATE jobs
            SET status = 'queued', run_at = now() + make_interval(secs => %s), locked_by = NULL,
                locked_at = NULL, last_error = %s
            WHERE id = %s AND status = 'running' AND locked_by = %s
            """,
            (backoff_s(job.attempts), code, job.id, worker),
        )
    else:
        cursor = connection.execute(
            """
            UPDATE jobs
            SET status = 'dead', finished_at = now(), locked_by = NULL, locked_at = NULL,
                last_error = %s
            WHERE id = %s AND status = 'running' AND locked_by = %s
            """,
            (code, job.id, worker),
        )
    return cursor.rowcount == 1


def recover(connection: Connection, timeout_s: int) -> tuple[int, int]:
    """Hands back the jobs of workers that died: how many were requeued, and how many were out of
    attempts. A replay that kills its worker every time therefore ends up dead, not in a loop."""
    dead = connection.execute(
        """
        UPDATE jobs
        SET status = 'dead', finished_at = now(), locked_by = NULL, locked_at = NULL,
            last_error = 'abandoned'
        WHERE status = 'running' AND locked_at < now() - make_interval(secs => %s)
            AND attempts >= max_attempts
        """,
        (timeout_s,),
    ).rowcount
    requeued = connection.execute(
        """
        UPDATE jobs
        SET status = 'queued', run_at = now(), locked_by = NULL, locked_at = NULL,
            last_error = 'abandoned'
        WHERE status = 'running' AND locked_at < now() - make_interval(secs => %s)
        """,
        (timeout_s,),
    ).rowcount
    return requeued, dead


def status_counts(connection: Connection) -> dict[tuple[str, str], int]:
    rows = connection.execute("SELECT kind, status, count(*) FROM jobs GROUP BY kind, status")
    return {(row[0], row[1]): row[2] for row in rows.fetchall()}


def dead_jobs(connection: Connection, limit: int = 20) -> list[tuple[int, str, str | None]]:
    """The latest dead jobs, for whoever looks after the queue: id, kind and failure code."""
    rows = connection.execute(
        "SELECT id, kind, last_error FROM jobs WHERE status = 'dead' "
        "ORDER BY finished_at DESC, id DESC LIMIT %s",
        (limit,),
    )
    return [(row[0], row[1], row[2]) for row in rows.fetchall()]
