"""`ma-worker`: runs the jobs, or says how the queue is doing."""

import argparse
import logging
import multiprocessing
import os
import shutil
import signal
import socket
import threading
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

import psycopg

from ma_worker import parse, queue
from ma_worker.queue import Connection
from ma_worker.runner import Handler, Runner
from ma_worker.settings import Settings, SettingsError
from ma_worker.store import S3Store


def build_handlers(settings: Settings) -> Mapping[str, Handler]:
    """A job of another kind waits in the queue until its handler gets written."""
    store = S3Store(settings)
    return {"parse": lambda connection, job: parse.handle(connection, job, store, settings)}


def resolve_parser(settings: Settings) -> Settings:
    """Looked up here, with the worker's `PATH`: the sandbox runs it with an empty environment, in
    another folder. Better to refuse to start than to fail every job."""
    found = shutil.which(settings.parser_bin)
    if found is None:
        raise SettingsError("PARSER_BIN is not an executable program")
    return replace(settings, parser_bin=str(Path(found).resolve()))


def _connect(settings: Settings) -> Connection:
    connection: Connection = psycopg.connect(settings.database_url, autocommit=True)
    return connection


def _serve(settings: Settings, index: int) -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    stop = threading.Event()
    for name in (signal.SIGTERM, signal.SIGINT):
        signal.signal(name, lambda *_: stop.set())
    worker = f"{socket.gethostname()}-{os.getpid()}-{index}"
    handlers = build_handlers(settings)
    Runner(lambda: _connect(settings), handlers, worker, settings.job_timeout_s).run(stop)


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
        run(resolve_parser(settings))
    else:
        status(settings)


if __name__ == "__main__":
    main()
