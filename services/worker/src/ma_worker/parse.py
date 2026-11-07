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

import ma_schemas
from ma_schemas import HeaderDocument
from ma_worker import dedupe, identify, load, sandbox
from ma_worker.queue import Connection, Job
from ma_worker.runner import PermanentError
from ma_worker.settings import Settings
from ma_worker.store import ObjectStore, TooLargeError

log = logging.getLogger("ma_worker")

_INPUT = "input.replay"
_HEADER = "header.json"
_CLASS_PREFIX = b"TAGame.Replay_"
_CLASS_SEARCH_BYTES = 256
_HEADER_MAX_BYTES = 5_242_880
_HASH_CHUNK_BYTES = 1_048_576
_OVER = ("done", "duplicate", "rejected", "failed")

_EXIT_OK = 0
_EXIT_BAD_ARGUMENTS = 2
_EXIT_NOT_A_REPLAY = 10
_EXIT_CORRUPT = 11
_EXIT_OUTPUT_ERROR = 15


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
    log.info("upload %s rejected: %s", upload.id, code)


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


def _read_header(workdir: Path) -> HeaderDocument:
    """A document the parser wrote from a stranger's file: checked like any other input."""
    path = workdir / _HEADER
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
        ["--header", "--input", _INPUT, "--output", _HEADER],
        workdir,
        sandbox.Limits(timeout_s=settings.parser_timeout_s, memory_mb=settings.parser_memory_mb),
    )
    code = result.exit_code
    if code == _EXIT_OK:
        return _read_header(workdir)
    if code == _EXIT_BAD_ARGUMENTS:
        raise PermanentError("parser_bad_arguments")
    if code == _EXIT_OUTPUT_ERROR:
        raise ParserOutputError
    if code == _EXIT_NOT_A_REPLAY:
        _reject(connection, store, upload, "not_a_replay")
        return None
    # Corrupt, or the parser panicked, ran out of memory or of time on a header, which takes well
    # under a second. Either way, this file gives no header and would do the same again.
    log.warning("upload %s: parser ended with %s", upload.id, "timeout" if code is None else code)
    _reject(connection, store, upload, "corrupt")
    return None


def _process(
    connection: Connection, store: ObjectStore, upload: Upload, settings: Settings, workdir: Path
) -> None:
    source = workdir / _INPUT
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

    # Before the transaction: once a match names this file, the file has to be there.
    target = raw_key(sha256)
    store.copy(upload.key, target)
    with connection.transaction():
        match_id = load.insert_match(connection, header, key, target)
        if match_id is not None:
            connection.execute(
                "INSERT INTO match_files (sha256, match_id) VALUES (%s, %s)", (sha256, match_id)
            )
            identify.link(connection, match_id, upload.user_id, upload.session_id)
            connection.execute(
                "UPDATE uploads SET status = 'done', sha256 = %s, match_id = %s, "
                "completed_at = now() WHERE id = %s",
                (sha256, match_id, upload.id),
            )
    if match_id is None:
        # Another worker created this match in the meantime, from another file.
        winner = load.existing_match(connection, key)
        assert winner is not None
        if winner[1] != target:
            store.delete(target)
        _attach_to_known_match(connection, store, upload, sha256, winner[0])
        return
    store.delete(upload.key)
    log.info("match %s from build %s", match_id, header["game_build"])


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
