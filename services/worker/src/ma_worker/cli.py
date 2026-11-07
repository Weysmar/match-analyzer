"""`ma-worker`: runs the jobs, or says how the queue is doing."""

import argparse
import logging
import multiprocessing
import os
import signal
import socket
import threading
from collections.abc import Mapping
from typing import Any

import psycopg

from ma_worker import queue
from ma_worker.queue import Connection
from ma_worker.runner import Handler, Runner
from ma_worker.settings import Settings

# Filled in as the jobs get written. A job of another kind waits in the queue.
HANDLERS: Mapping[str, Handler] = {}


def _connect(settings: Settings) -> Connection:
    connection: Connection = psycopg.connect(settings.database_url, autocommit=True)
    return connection


def _serve(settings: Settings, index: int) -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    stop = threading.Event()
    for name in (signal.SIGTERM, signal.SIGINT):
        signal.signal(name, lambda *_: stop.set())
    worker = f"{socket.gethostname()}-{os.getpid()}-{index}"
    Runner(lambda: _connect(settings), HANDLERS, worker, settings.job_timeout_s).run(stop)


def run(settings: Settings) -> None:
    """One process per worker: the sandbox rules out threads."""
    if settings.concurrency == 1:
        _serve(settings, 0)
        return
    context = multiprocessing.get_context("spawn")
    processes: list[Any] = [
        context.Process(target=_serve, args=(settings, index))
        for index in range(settings.concurrency)
    ]
    for process in processes:
        process.start()
    for name in (signal.SIGTERM, signal.SIGINT):
        signal.signal(name, lambda *_: [process.terminate() for process in processes])
    for process in processes:
        process.join()


def status(settings: Settings) -> None:
    """Dead jobs have to be seen: nothing else will bring them back."""
    with _connect(settings) as connection:
        for (kind, state), count in sorted(queue.status_counts(connection).items()):
            print(f"{kind:10} {state:8} {count}")
        for job_id, kind, code in queue.dead_jobs(connection):
            print(f"dead: job {job_id} ({kind}): {code}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="ma-worker", description=__doc__)
    parser.add_argument("command", choices=["run", "status"])
    arguments = parser.parse_args()
    settings = Settings.from_env()
    if arguments.command == "run":
        run(settings)
    else:
        status(settings)


if __name__ == "__main__":
    main()
