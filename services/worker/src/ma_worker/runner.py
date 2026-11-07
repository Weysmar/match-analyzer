"""The worker's loop: take a job, run it, write down what happened."""

import logging
import threading
import time
from collections.abc import Callable, Mapping

import psycopg

from ma_worker import queue
from ma_worker.queue import Connection, Job

log = logging.getLogger("ma_worker")

type Handler = Callable[[Connection, Job], None]

_RECONNECT_WAIT_S = 5.0


class PermanentError(Exception):
    """Trying again would give the same result: the job goes straight to dead."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class Runner:
    def __init__(
        self,
        connect: Callable[[], Connection],
        handlers: Mapping[str, Handler],
        worker: str,
        job_timeout_s: int,
        *,
        poll_s: float = 2.0,
        recover_every_s: float = 60.0,
    ) -> None:
        self._connect = connect
        self._handlers = handlers
        self._worker = worker
        self._job_timeout_s = job_timeout_s
        self._poll_s = poll_s
        self._recover_every_s = recover_every_s
        self._last_recovery = float("-inf")

    def run_once(self, connection: Connection) -> bool:
        """Runs one job if there is one. Logs never quote an exception's text: it can hold a
        player's name. A lost connection goes up to `run`, and the job comes back through
        `recover`, since nobody can write down its outcome."""
        job = queue.claim(connection, self._worker, list(self._handlers))
        if job is None:
            return False
        try:
            self._handlers[job.kind](connection, job)
        except PermanentError as failure:
            log.warning("job %d (%s) failed for good: %s", job.id, job.kind, failure.code)
            queue.fail(connection, job, self._worker, failure.code, retry=False)
        except psycopg.OperationalError:
            raise
        except Exception as error:
            code = type(error).__name__
            log.warning("job %d (%s) failed: %s", job.id, job.kind, code)
            queue.fail(connection, job, self._worker, code)
        else:
            if not queue.finish(connection, job, self._worker):
                log.warning("job %d (%s) was no longer ours", job.id, job.kind)
        return True

    def _recover_if_due(self, connection: Connection) -> None:
        now = time.monotonic()
        if now - self._last_recovery < self._recover_every_s:
            return
        self._last_recovery = now
        requeued, dead = queue.recover(connection, self._job_timeout_s)
        if requeued or dead:
            log.warning("abandoned jobs: %d requeued, %d dead", requeued, dead)

    def run(self, stop: threading.Event) -> None:
        """Until `stop` is set, which lets the current job finish. Survives losing the database."""
        while not stop.is_set():
            try:
                with self._connect() as connection:
                    while not stop.is_set():
                        self._recover_if_due(connection)
                        if not self.run_once(connection):
                            stop.wait(self._poll_s)
            except psycopg.OperationalError as error:
                log.warning("database unreachable: %s", type(error).__name__)
                stop.wait(_RECONNECT_WAIT_S)
