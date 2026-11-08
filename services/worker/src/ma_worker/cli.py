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

from ma_worker import analyze, parse, queue, reparse, reprocess
from ma_worker.queue import Connection
from ma_worker.runner import Handler, Runner
from ma_worker.settings import Settings, SettingsError
from ma_worker.store import S3Store


def build_handlers(settings: Settings) -> Mapping[str, Handler]:
    """A job of another kind waits in the queue until its handler gets written."""
    store = S3Store(settings)
    return {
        "parse": lambda connection, job: parse.handle(connection, job, store, settings),
        "analyze": lambda connection, job: analyze.handle(connection, job, store, settings),
        "reparse": lambda connection, job: reparse.handle(connection, job, store, settings),
    }


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


def reprocess_command(settings: Settings, arguments: argparse.Namespace) -> None:
    with _connect(settings) as connection:
        if arguments.parser_outdated:
            version = reprocess.parser_version(settings)
            print(f"parser in use: {version}")
            summary = reprocess.parser_outdated(
                connection,
                version,
                build_from=arguments.build_from,
                build_to=arguments.build_to,
                dry_run=arguments.dry_run,
            )
        else:
            summary = reprocess.analysis_outdated(
                connection,
                build_from=arguments.build_from,
                build_to=arguments.build_to,
                dry_run=arguments.dry_run,
            )
    print(reprocess.report(summary, dry_run=arguments.dry_run))


def parser() -> argparse.ArgumentParser:
    command_line = argparse.ArgumentParser(prog="ma-worker", description=__doc__)
    commands = command_line.add_subparsers(dest="command", required=True)
    commands.add_parser("run", help="run the jobs")
    commands.add_parser("status", help="how the queue is doing, dead jobs included")
    again = commands.add_parser("reprocess", help="queue the outdated matches again")
    which = again.add_mutually_exclusive_group(required=True)
    which.add_argument("--parser-outdated", action="store_true")
    which.add_argument("--analysis-outdated", action="store_true")
    again.add_argument("--build-from", type=int, help="the game's BuildID, inclusive")
    again.add_argument("--build-to", type=int, help="the game's BuildID, inclusive")
    again.add_argument("--dry-run", action="store_true", help="say what would be queued")
    return command_line


def main(argv: list[str] | None = None) -> None:
    arguments = parser().parse_args(argv)
    settings = Settings.from_env()
    if arguments.command == "run":
        run(resolve_parser(settings))
    elif arguments.command == "status":
        status(settings)
    else:
        reprocess_command(resolve_parser(settings), arguments)


if __name__ == "__main__":
    main()
