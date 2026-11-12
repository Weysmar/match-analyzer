"""The `parse` job: from a file dropped by a stranger to a match in the database.

It can run again at any point: a worker may die anywhere in between. Every step is therefore safe to
repeat, and a file only leaves `incoming/` once the database says what became of it.
"""

import hashlib
import json
import logging
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from psycopg.types.json import Jsonb

import ma_schemas
from ma_schemas import EventsDocument, HeaderDocument
from ma_worker import dedupe, identify, load, sandbox
from ma_worker.queue import Connection, Job
from ma_worker.runner import PermanentError
from ma_worker.settings import Settings
from ma_worker.store import ObjectStore, TooLargeError

log = logging.getLogger("ma_worker")

INPUT = "input.replay"
HEADER = "header.json"
_OUTPUT_FOLDER = "out"
_FRAMES = "frames.parquet"
_EVENTS = "events.json"
_CLASS_PREFIX = b"TAGame.Replay_"
_CLASS_SEARCH_BYTES = 256
_HEADER_MAX_BYTES = 5_242_880
_EVENTS_MAX_BYTES = 268_435_456
_HASH_CHUNK_BYTES = 1_048_576
_OVER = ("done", "duplicate", "rejected", "failed")

EXIT_OK = 0
_EXIT_BAD_ARGUMENTS = 2
_EXIT_NOT_A_REPLAY = 10
_EXIT_CORRUPT = 11
EXIT_OUTPUT_ERROR = 15
# What a failed read of the network stream is called in `matches.error_code`.
_FRAMES_FAILURES = {12: "network_failed", 13: "processor_failed", 14: "unsupported_mode"}


class ParserOutputError(Exception):
    """The parser could not write its output: worth another try."""


@dataclass(frozen=True)
class Upload:
    id: uuid.UUID
    status: str
    declared_size: int
    user_id: uuid.UUID | None
    session_id: uuid.UUID | None

    @property
    def key(self) -> str:
        return incoming_key(self.id)


def incoming_key(upload_id: uuid.UUID) -> str:
    return f"incoming/{upload_id}"


def raw_key(sha256: str) -> str:
    return f"raw/{sha256}.replay"


def looks_like_a_replay(path: Path) -> bool:
    """Spares the sandbox an obvious fake. The parser checks again, and more."""
    with path.open("rb") as file:
        return _CLASS_PREFIX in file.read(_CLASS_SEARCH_BYTES)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(_HASH_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def _load_upload(connection: Connection, upload_id: uuid.UUID) -> Upload | None:
    row = connection.execute(
        "SELECT id, status, declared_size, user_id, anonymous_session_id FROM uploads "
        "WHERE id = %s",
        (upload_id,),
    ).fetchone()
    return None if row is None else Upload(row[0], row[1], row[2], row[3], row[4])


def _reject(connection: Connection, store: ObjectStore, upload: Upload, code: str) -> None:
    """The file is at fault, not the job: it ends well, with a refused file."""
    connection.execute(
        "UPDATE uploads SET status = 'rejected', rejection = %s, completed_at = now() "
        "WHERE id = %s",
        (code, upload.id),
    )
    store.delete(upload.key)
    log.info(
        "upload %s rejected: %s",
        upload.id,
        code,
        extra={"event": "upload_rejected", "upload_id": upload.id, "code": code},
    )


def _attach_to_known_match(
    connection: Connection,
    store: ObjectStore,
    upload: Upload,
    sha256: str,
    match_id: uuid.UUID,
) -> None:
    """Only the first file of a match is kept."""
    with connection.transaction():
        connection.execute(
            "INSERT INTO match_files (sha256, match_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (sha256, match_id),
        )
        identify.link(connection, match_id, upload.user_id, upload.session_id)
        connection.execute(
            "UPDATE uploads SET status = 'duplicate', sha256 = %s, match_id = %s, "
            "completed_at = now() WHERE id = %s",
            (sha256, match_id, upload.id),
        )
    store.delete(upload.key)


def read_header(workdir: Path) -> HeaderDocument:
    """A document the parser wrote from a stranger's file: checked like any other input."""
    path = workdir / HEADER
    try:
        if path.stat().st_size > _HEADER_MAX_BYTES:
            raise PermanentError("invalid_header")
        document: Any = json.loads(path.read_bytes())
        return ma_schemas.parse_header(document)
    except OSError, ValueError:
        raise PermanentError("invalid_header") from None


def _run_header(
    connection: Connection, store: ObjectStore, upload: Upload, settings: Settings, workdir: Path
) -> HeaderDocument | None:
    """The header, or None when the file was rejected."""
    result = sandbox.run(
        settings.parser_bin,
        ["--header", "--input", INPUT, "--output", HEADER],
        workdir,
        sandbox.Limits(timeout_s=settings.parser_timeout_s, memory_mb=settings.parser_memory_mb),
    )
    code = result.exit_code
    if code == EXIT_OK:
        return read_header(workdir)
    if code == _EXIT_BAD_ARGUMENTS:
        raise PermanentError("parser_bad_arguments")
    if code == EXIT_OUTPUT_ERROR:
        raise ParserOutputError
    if code == _EXIT_NOT_A_REPLAY:
        _reject(connection, store, upload, "not_a_replay")
        return None
    # Corrupt, or the parser panicked, ran out of memory or of time on a header, which takes well
    # under a second. Either way, this file gives no header and would do the same again.
    ended = "timeout" if code is None else code
    log.warning(
        "upload %s: parser ended with %s",
        upload.id,
        ended,
        extra={"event": "header_unreadable", "upload_id": upload.id, "code": ended},
    )
    _reject(connection, store, upload, "corrupt")
    return None


def frames_key(match_id: uuid.UUID) -> str:
    return f"frames/{match_id}.parquet"


def events_key(match_id: uuid.UUID) -> str:
    return f"events/{match_id}.json"


def _read_events(output: Path) -> EventsDocument | None:
    """None when the files are not what they should be: a patch can do this, and it must not cost
    the match its header."""
    path = output / _EVENTS
    try:
        if path.stat().st_size > _EVENTS_MAX_BYTES or (output / _FRAMES).stat().st_size == 0:
            return None
        return ma_schemas.parse_events(json.loads(path.read_bytes()))
    except OSError, ValueError:
        return None


def run_frames(
    store: ObjectStore,
    settings: Settings,
    workdir: Path,
    match_id: uuid.UUID,
) -> tuple[load.Frames | None, str | None]:
    """The network stream, with the files stored, or the reason it cannot be read."""
    output = workdir / _OUTPUT_FOLDER
    output.mkdir()
    arguments = ["--frames", "--input", INPUT, "--output-dir", _OUTPUT_FOLDER]
    if settings.parser_max_fps is not None:
        arguments += ["--fps", str(settings.parser_max_fps)]
    result = sandbox.run(
        settings.parser_bin,
        arguments,
        workdir,
        sandbox.Limits(timeout_s=settings.parser_timeout_s, memory_mb=settings.parser_memory_mb),
    )
    code = result.exit_code
    if code == _EXIT_BAD_ARGUMENTS:
        raise PermanentError("parser_bad_arguments")
    if code == EXIT_OUTPUT_ERROR:
        raise ParserOutputError
    if code != EXIT_OK:
        if result.timed_out:
            return None, "parser_timeout"
        # A panic, or running out of memory: this file would only do the same again.
        return None, _FRAMES_FAILURES.get(code if code is not None else -1, "parser_crashed")
    events = _read_events(output)
    if events is None:
        return None, "invalid_events"
    frames = load.Frames(events, frames_key(match_id), events_key(match_id))
    store.upload(output / _FRAMES, frames.frames_key, "application/vnd.apache.parquet")
    store.upload(output / _EVENTS, frames.events_key, "application/json")
    return frames, None


def _process(
    connection: Connection, store: ObjectStore, upload: Upload, settings: Settings, workdir: Path
) -> None:
    source = workdir / INPUT
    try:
        store.download(upload.key, source, settings.upload_max_bytes)
    except TooLargeError:
        _reject(connection, store, upload, "too_large")
        return
    if source.stat().st_size != upload.declared_size:
        _reject(connection, store, upload, "size_mismatch")
        return
    if not looks_like_a_replay(source):
        _reject(connection, store, upload, "not_a_replay")
        return

    # The real hash, computed here: the one the browser gave is never trusted.
    sha256 = file_sha256(source)
    known = connection.execute(
        "SELECT match_id FROM match_files WHERE sha256 = %s", (sha256,)
    ).fetchone()
    if known is not None:
        _attach_to_known_match(connection, store, upload, sha256, known[0])
        return

    header = _run_header(connection, store, upload, settings, workdir)
    if header is None:
        return
    key = dedupe.dedupe_key(header, sha256)
    existing = load.existing_match(connection, key)
    if existing is not None:
        _attach_to_known_match(connection, store, upload, sha256, existing[0])
        return

    # All of this before the transaction: once a match names its files, they have to be there. If
    # the worker dies here, the job starts over and writes over the same keys.
    match_id = load.match_id_for(key)
    target = raw_key(sha256)
    store.copy(upload.key, target)
    frames, error_code = run_frames(store, settings, workdir, match_id)
    with connection.transaction():
        created = load.insert_match(connection, match_id, header, key, target, frames, error_code)
        if created:
            connection.execute(
                "INSERT INTO match_files (sha256, match_id) VALUES (%s, %s)", (sha256, match_id)
            )
            identify.link(connection, match_id, upload.user_id, upload.session_id)
            connection.execute(
                "UPDATE uploads SET status = 'done', sha256 = %s, match_id = %s, "
                "completed_at = now() WHERE id = %s",
                (sha256, match_id, upload.id),
            )
            if frames is not None:
                connection.execute(
                    "INSERT INTO jobs (kind, payload) VALUES ('analyze', %s)",
                    (Jsonb({"match_id": str(match_id)}),),
                )
    if not created:
        # Another worker created this match in the meantime, from another file.
        winner = load.existing_match(connection, key)
        assert winner is not None
        if winner[1] != target:
            store.delete(target)
        _attach_to_known_match(connection, store, upload, sha256, winner[0])
        return
    store.delete(upload.key)
    # The build goes to the log either way: this is how a breaking patch shows up.
    if frames is None:
        log.warning(
            "match %s from build %s: %s",
            match_id,
            header["game_build"],
            error_code,
            extra={
                "event": "parsed",
                "match_id": match_id,
                "build": header["game_build"],
                "status": "header_only",
                "code": error_code,
            },
        )
    else:
        log.info(
            "match %s from build %s",
            match_id,
            header["game_build"],
            extra={
                "event": "parsed",
                "match_id": match_id,
                "build": header["game_build"],
                "status": "parsed",
            },
        )


def handle(connection: Connection, job: Job, store: ObjectStore, settings: Settings) -> None:
    try:
        upload_id = uuid.UUID(job.payload["upload_id"])
    except KeyError, ValueError, TypeError, AttributeError:
        raise PermanentError("bad_payload") from None
    upload = _load_upload(connection, upload_id)
    if upload is None or upload.status in _OVER:
        # Erased in the meantime, or already dealt with by an attempt that died right after: only
        # the file may be left.
        store.delete(incoming_key(upload_id))
        return
    connection.execute("UPDATE uploads SET status = 'processing' WHERE id = %s", (upload_id,))
    with tempfile.TemporaryDirectory(prefix="ma-parse-") as folder:
        _process(connection, store, upload, settings, Path(folder))
