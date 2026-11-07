"""The queue and the loop, against PostgreSQL with the worker's own role."""

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Any

import psycopg
import pytest

from ma_db.testing import Connection, Factory
from ma_worker import queue
from ma_worker.queue import Job
from ma_worker.runner import PermanentError, Runner

pytestmark = pytest.mark.db

ME = "worker-a"
KINDS = ["parse"]


def add_job(conn: Connection, kind: str = "parse", **columns: Any) -> int:
    names = ["kind", *columns]
    placeholders = ", ".join(["%s"] * len(names))
    row = conn.execute(
        f"INSERT INTO jobs ({', '.join(names)}) VALUES ({placeholders}) RETURNING id".encode(),
        [kind, *columns.values()],
    ).fetchone()
    assert row is not None
    return int(row[0])


def state(conn: Connection, job_id: int) -> dict[str, Any]:
    row = conn.execute(
        "SELECT status, attempts, locked_by, last_error, finished_at IS NOT NULL, run_at - now() "
        "FROM jobs WHERE id = %s",
        (job_id,),
    ).fetchone()
    assert row is not None
    names = ("status", "attempts", "locked_by", "last_error", "finished", "delay")
    return dict(zip(names, row, strict=True))


def take(worker_conn: Connection, worker: str = ME) -> Job:
    job = queue.claim(worker_conn, worker, KINDS)
    assert job is not None
    return job


@pytest.mark.parametrize(
    ("attempts", "seconds"), [(1, 30), (2, 120), (3, 480), (4, 1920), (5, 3600), (50, 3600)]
)
def test_backoff_grows_and_stops_growing(attempts: int, seconds: int) -> None:
    assert queue.backoff_s(attempts) == seconds


def test_claiming_takes_the_job(conn: Connection, worker_conn: Connection) -> None:
    job_id = add_job(conn, payload='{"upload_id": "an-id"}')
    job = take(worker_conn)
    assert job == Job(job_id, "parse", {"upload_id": "an-id"}, 1, 3)
    current = state(conn, job_id)
    assert (current["status"], current["locked_by"]) == ("running", ME)


def test_nothing_to_claim(conn: Connection, worker_conn: Connection) -> None:
    assert queue.claim(worker_conn, ME, KINDS) is None


def test_a_job_is_only_claimed_once(conn: Connection, worker_conn: Connection) -> None:
    add_job(conn)
    take(worker_conn)
    assert queue.claim(worker_conn, "worker-b", KINDS) is None


def test_other_kinds_wait(conn: Connection, worker_conn: Connection) -> None:
    add_job(conn, "gc_match")
    assert queue.claim(worker_conn, ME, KINDS) is None
    assert queue.claim(worker_conn, ME, []) is None


def test_priority_comes_first(conn: Connection, worker_conn: Connection) -> None:
    add_job(conn, priority=0)
    urgent = add_job(conn, priority=5)
    assert take(worker_conn).id == urgent


def test_a_job_for_later_waits(conn: Connection, worker_conn: Connection) -> None:
    add_job(conn, run_at="infinity")
    assert queue.claim(worker_conn, ME, KINDS) is None


def test_workers_side_by_side_never_share_a_job(conn: Connection, worker_url: str) -> None:
    jobs = [add_job(conn) for _ in range(60)]

    def drain(worker: str) -> list[int]:
        taken = []
        with psycopg.connect(worker_url, autocommit=True) as connection:
            while (job := queue.claim(connection, worker, KINDS)) is not None:
                taken.append(job.id)
        return taken

    with ThreadPoolExecutor(4) as pool:
        results = list(pool.map(drain, [f"worker-{index}" for index in range(4)]))
    taken = [job for result in results for job in result]
    assert sorted(taken) == sorted(jobs)


def test_finishing(conn: Connection, worker_conn: Connection) -> None:
    job_id = add_job(conn, last_error="an old failure")
    job = take(worker_conn)
    assert queue.finish(worker_conn, job, ME) is True
    current = state(conn, job_id)
    assert current["status"] == "done"
    assert current["finished"] is True
    assert current["locked_by"] is None
    assert current["last_error"] is None


def test_a_failure_comes_back_later(conn: Connection, worker_conn: Connection) -> None:
    job_id = add_job(conn)
    job = take(worker_conn)
    assert queue.fail(worker_conn, job, ME, "StoreError") is True
    current = state(conn, job_id)
    assert current["status"] == "queued"
    assert current["last_error"] == "StoreError"
    assert current["locked_by"] is None
    assert timedelta(seconds=25) < current["delay"] <= timedelta(seconds=30)
    assert queue.claim(worker_conn, ME, KINDS) is None


def test_out_of_attempts_is_dead(conn: Connection, worker_conn: Connection) -> None:
    job_id = add_job(conn, max_attempts=1)
    job = take(worker_conn)
    queue.fail(worker_conn, job, ME, "StoreError")
    current = state(conn, job_id)
    assert current["status"] == "dead"
    assert current["finished"] is True
    assert queue.dead_jobs(worker_conn) == [(job_id, "parse", "StoreError")]


def test_a_permanent_failure_does_not_come_back(conn: Connection, worker_conn: Connection) -> None:
    job_id = add_job(conn)
    job = take(worker_conn)
    queue.fail(worker_conn, job, ME, "bad_arguments", retry=False)
    assert state(conn, job_id)["status"] == "dead"


def test_a_slow_worker_cannot_overwrite_the_next_one(
    conn: Connection, worker_conn: Connection
) -> None:
    job_id = add_job(conn)
    slow = take(worker_conn, "slow")
    conn.execute("UPDATE jobs SET locked_at = now() - interval '1 hour' WHERE id = %s", (job_id,))
    assert queue.recover(worker_conn, 600) == (1, 0)
    take(worker_conn, "next")
    assert queue.finish(worker_conn, slow, "slow") is False
    assert queue.fail(worker_conn, slow, "slow", "StoreError") is False
    current = state(conn, job_id)
    assert (current["status"], current["locked_by"]) == ("running", "next")


def test_an_abandoned_job_is_taken_up_again(conn: Connection, worker_conn: Connection) -> None:
    job_id = add_job(conn)
    take(worker_conn, "died")
    conn.execute("UPDATE jobs SET locked_at = now() - interval '1 hour' WHERE id = %s", (job_id,))
    assert queue.recover(worker_conn, 600) == (1, 0)
    current = state(conn, job_id)
    assert (current["status"], current["last_error"]) == ("queued", "abandoned")
    assert take(worker_conn).attempts == 2


def test_a_recent_job_is_not_abandoned(conn: Connection, worker_conn: Connection) -> None:
    job_id = add_job(conn)
    take(worker_conn)
    assert queue.recover(worker_conn, 600) == (0, 0)
    assert state(conn, job_id)["status"] == "running"


def test_a_job_that_keeps_killing_workers_ends_up_dead(
    conn: Connection, worker_conn: Connection
) -> None:
    job_id = add_job(conn)
    for _ in range(3):
        take(worker_conn, "died")
        conn.execute(
            "UPDATE jobs SET locked_at = now() - interval '1 hour' WHERE id = %s", (job_id,)
        )
        queue.recover(worker_conn, 600)
    current = state(conn, job_id)
    assert (current["status"], current["last_error"]) == ("dead", "abandoned")


def test_counts_by_status(conn: Connection, worker_conn: Connection) -> None:
    add_job(conn)
    add_job(conn)
    add_job(conn, "gc_match")
    take(worker_conn)
    assert queue.status_counts(worker_conn) == {
        ("parse", "running"): 1,
        ("parse", "queued"): 1,
        ("gc_match", "queued"): 1,
    }


def runner_for(worker_url: str, **handlers: Any) -> Runner:
    return Runner(
        lambda: psycopg.connect(worker_url, autocommit=True),
        handlers,
        ME,
        600,
        poll_s=0.01,
        recover_every_s=0.01,
    )


def test_a_job_runs_and_finishes(
    conn: Connection, worker_conn: Connection, worker_url: str
) -> None:
    job_id = add_job(conn, payload='{"upload_id": "an-id"}')
    seen: list[Job] = []
    assert runner_for(worker_url, parse=lambda _, job: seen.append(job)).run_once(worker_conn)
    assert seen[0].payload == {"upload_id": "an-id"}
    assert state(conn, job_id)["status"] == "done"


def test_no_job_is_said_so(conn: Connection, worker_conn: Connection, worker_url: str) -> None:
    assert runner_for(worker_url, parse=lambda *_: None).run_once(worker_conn) is False


def test_a_crash_is_retried_and_its_text_kept_out(
    conn: Connection,
    worker_conn: Connection,
    worker_url: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    job_id = add_job(conn)

    def crash(*_: Any) -> None:
        raise ValueError("the name of a player")

    runner_for(worker_url, parse=crash).run_once(worker_conn)
    current = state(conn, job_id)
    assert (current["status"], current["last_error"]) == ("queued", "ValueError")
    assert "the name of a player" not in caplog.text


def test_a_permanent_failure_goes_straight_to_dead(
    conn: Connection, worker_conn: Connection, worker_url: str
) -> None:
    job_id = add_job(conn)

    def refuse(*_: Any) -> None:
        raise PermanentError("bad_arguments")

    runner_for(worker_url, parse=refuse).run_once(worker_conn)
    current = state(conn, job_id)
    assert (current["status"], current["last_error"]) == ("dead", "bad_arguments")
    assert current["attempts"] == 1


def test_a_lost_connection_goes_up_and_leaves_the_job_to_recovery(
    conn: Connection, worker_conn: Connection, worker_url: str
) -> None:
    job_id = add_job(conn)

    def lose(*_: Any) -> None:
        raise psycopg.OperationalError("the connection is gone")

    with pytest.raises(psycopg.OperationalError):
        runner_for(worker_url, parse=lose).run_once(worker_conn)
    assert state(conn, job_id)["status"] == "running"


def test_the_loop_runs_until_told_to_stop(conn: Connection, worker_url: str) -> None:
    jobs = [add_job(conn) for _ in range(3)]
    stop = threading.Event()

    def handle(*_: Any) -> None:
        done = conn.execute("SELECT count(*) FROM jobs WHERE status = 'done'").fetchone()
        assert done is not None
        if done[0] == 2:
            stop.set()

    runner_for(worker_url, parse=handle).run(stop)
    assert {state(conn, job_id)["status"] for job_id in jobs} == {"done"}


def test_the_loop_recovers_abandoned_jobs(
    conn: Connection, worker_conn: Connection, worker_url: str
) -> None:
    job_id = add_job(conn)
    take(worker_conn, "died")
    conn.execute("UPDATE jobs SET locked_at = now() - interval '1 hour' WHERE id = %s", (job_id,))
    stop = threading.Event()
    runner_for(worker_url, parse=lambda *_: stop.set()).run(stop)
    assert state(conn, job_id)["status"] == "done"


def test_the_loop_survives_losing_the_database(
    conn: Connection, worker_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    job_id = add_job(conn)
    stop = threading.Event()
    attempts: list[int] = []

    def connect() -> Connection:
        attempts.append(1)
        if len(attempts) == 1:
            raise psycopg.OperationalError("unreachable")
        connection: Connection = psycopg.connect(worker_url, autocommit=True)
        return connection

    monkeypatch.setattr("ma_worker.runner._RECONNECT_WAIT_S", 0.01)
    Runner(connect, {"parse": lambda *_: stop.set()}, ME, 600, poll_s=0.01).run(stop)
    assert len(attempts) == 2
    assert state(conn, job_id)["status"] == "done"


def test_the_worker_role_cannot_touch_accounts(worker_conn: Connection) -> None:
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        worker_conn.execute("DELETE FROM users")
    assert worker_conn.execute("SELECT count(*) FROM jobs").fetchone() is not None


def upload_status(conn: Connection, upload: object) -> str:
    row = conn.execute("SELECT status FROM uploads WHERE id = %s", (upload,)).fetchone()
    assert row is not None
    return str(row[0])


def test_a_job_that_keeps_killing_workers_fails_its_upload(
    conn: Connection, worker_conn: Connection, make: Factory
) -> None:
    upload = make.upload(anonymous_session_id=make.anonymous_session())
    conn.execute("UPDATE uploads SET status = 'processing' WHERE id = %s", (upload,))
    job_id = add_job(conn, payload=f'{{"upload_id": "{upload}"}}', max_attempts=1)
    take(worker_conn, "died")
    conn.execute("UPDATE jobs SET locked_at = now() - interval '1 hour' WHERE id = %s", (job_id,))
    assert queue.recover(worker_conn, 600) == (0, 1)
    assert upload_status(conn, upload) == "failed"


def test_a_retry_leaves_its_upload_alone(
    conn: Connection, worker_conn: Connection, make: Factory
) -> None:
    upload = make.upload(anonymous_session_id=make.anonymous_session())
    conn.execute("UPDATE uploads SET status = 'processing' WHERE id = %s", (upload,))
    add_job(conn, payload=f'{{"upload_id": "{upload}"}}')
    queue.fail(worker_conn, take(worker_conn), ME, "StoreError")
    assert upload_status(conn, upload) == "processing"


def test_a_finished_upload_is_not_marked_failed(
    conn: Connection, worker_conn: Connection, make: Factory
) -> None:
    upload = make.upload(anonymous_session_id=make.anonymous_session())
    conn.execute("UPDATE uploads SET status = 'done' WHERE id = %s", (upload,))
    add_job(conn, payload=f'{{"upload_id": "{upload}"}}', max_attempts=1)
    queue.fail(worker_conn, take(worker_conn), ME, "StoreError")
    assert upload_status(conn, upload) == "done"
