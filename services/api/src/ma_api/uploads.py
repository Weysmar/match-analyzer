"""Uploads: the browser sends each file straight to the object store, then says it is done.

A declared hash is never trusted. It only spots a file this same owner has already brought, compared
with the hash the worker computed: otherwise, knowing a hash would be enough to obtain a match.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Request, Response
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field, field_validator

from ma_api import models, pagination, ratelimit, sessions
from ma_api.db import Connection, ConnectionDep, Database
from ma_api.errors import ApiError, not_found
from ma_api.owner import Owner
from ma_api.sessions import IdentityDep, SettingsDep
from ma_api.settings import Settings
from ma_api.storage import CONTENT_TYPE, ObjectStore

_NAME_MAX = 255
_SHA256 = r"^[0-9a-f]{64}$"
_LIST_MAX = 200

UploadStatus = Literal[
    "awaiting_file", "uploaded", "processing", "done", "duplicate", "rejected", "failed"
]


class FileIn(BaseModel):
    name: str = Field(min_length=1, max_length=_NAME_MAX)
    size: int = Field(gt=0)
    sha256: str | None = Field(default=None, pattern=_SHA256)

    @field_validator("name")
    @classmethod
    def printable(cls, value: str) -> str:
        if not value.isprintable():
            raise ValueError("not printable")
        return value


class BatchIn(BaseModel):
    files: list[FileIn] = Field(min_length=1)


def _check_batch(batch: BatchIn, settings: Settings) -> None:
    """Before anything is written: a refused batch leaves nothing behind."""
    if len(batch.files) > settings.upload_max_files:
        raise ApiError(422, "too_many_files", {"max_files": settings.upload_max_files})
    if any(file.size > settings.upload_max_bytes for file in batch.files):
        raise ApiError(413, "too_large", {"max_bytes": settings.upload_max_bytes})


def _already_mine(
    connection: Connection, owner: Owner, batch: BatchIn
) -> dict[str, tuple[uuid.UUID, uuid.UUID]]:
    """Per real hash, one of the owner's uploads that holds it and its match."""
    hashes = [file.sha256 for file in batch.files if file.sha256 is not None]
    if not hashes:
        return {}
    query = sql.SQL(
        "SELECT sha256::text, id, match_id FROM uploads "
        "WHERE {} AND match_id IS NOT NULL AND sha256::text = ANY(%s)"
    ).format(owner.condition)
    rows = connection.execute(query, (hashes,)).fetchall()
    return {row[0]: (row[1], row[2]) for row in rows}


def _quotas(owner: Owner, request: Request, settings: Settings) -> list[tuple[str, int]]:
    quotas = [
        (ratelimit.address_key(request, settings, "upload"), settings.rate_upload_ip_per_day),
    ]
    if owner.user_id is not None:
        quotas.append((f"upload:user:{owner.user_id}", settings.rate_upload_user_per_day))
    else:
        quotas.append(
            (f"upload:anon:{owner.anonymous_session_id}", settings.rate_upload_anon_per_day)
        )
    return quotas


def _store(request: Request) -> ObjectStore:
    store: ObjectStore = request.app.state.storage
    return store


router = APIRouter()


@router.post("/uploads", status_code=201, response_model=models.UploadsCreated)
def create(
    batch: BatchIn,
    request: Request,
    response: Response,
    connection: ConnectionDep,
    settings: SettingsDep,
    identity: IdentityDep,
) -> dict[str, list[dict[str, Any]]]:
    """Opens one upload per file. The first one opens the anonymous session of a new visitor."""
    _check_batch(batch, settings)
    owner = sessions.ensure_owner(connection, settings, identity, response)
    known = _already_mine(connection, owner, batch)
    new = [file for file in batch.files if file.sha256 not in known]
    if new:
        ratelimit.consume(connection, _quotas(owner, request, settings), len(new), 86_400)

    store = _store(request)
    expires_at = datetime.now(UTC) + timedelta(seconds=settings.upload_url_ttl_s)
    uploads: list[dict[str, Any]] = []
    for file in batch.files:
        if file.sha256 in known:
            upload_id, match_id = known[file.sha256]
            uploads.append(
                {"upload_id": str(upload_id), "status": "duplicate", "match_id": str(match_id)}
            )
            continue
        upload_id = uuid.uuid4()
        key = f"incoming/{upload_id}"
        connection.execute(
            "INSERT INTO uploads (id, user_id, anonymous_session_id, file_name, declared_size, "
            "declared_sha256, incoming_key) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (
                upload_id,
                owner.user_id,
                owner.anonymous_session_id,
                file.name,
                file.size,
                file.sha256,
                key,
            ),
        )
        uploads.append(
            {
                "upload_id": str(upload_id),
                "status": "awaiting_file",
                "url": store.presign_put(key, file.size),
                "method": "PUT",
                "headers": {"Content-Type": CONTENT_TYPE},
                "expires_at": expires_at.isoformat(),
            }
        )
    return {"uploads": uploads}


# The match's own state comes along: following a batch takes one request, whatever its size.
_COLUMNS = sql.SQL(
    "id, file_name, status, rejection, match_id, created_at, "
    "(SELECT m.status FROM matches m WHERE m.id = uploads.match_id) AS match_status"
)


def _item(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "upload_id": str(row["id"]),
        "name": row["file_name"],
        "status": row["status"],
        "rejection": row["rejection"],
        "match_id": None if row["match_id"] is None else str(row["match_id"]),
        "match_status": row["match_status"],
    }


def _owned_upload(connection: Connection, owner: Owner, upload_id: uuid.UUID) -> dict[str, Any]:
    """Someone else's upload looks like one that does not exist."""
    query = sql.SQL(
        "SELECT status, incoming_key, declared_size FROM uploads WHERE id = %s AND {}"
    ).format(owner.condition)
    with connection.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute(query, (upload_id,)).fetchone()
    if row is None:
        raise not_found()
    return row


def _invalid_state(status: str) -> ApiError:
    return ApiError(409, "invalid_state", {"status": status})


@router.post(
    "/uploads/{upload_id}/complete", status_code=202, response_model=models.UploadCompleted
)
def complete(upload_id: uuid.UUID, request: Request, settings: SettingsDep) -> dict[str, str]:
    """Checks that the file arrived, then queues it. No connection stays held while asking the
    object store: a slow store would use up the pool and stop the whole API."""
    database: Database = request.app.state.database
    with database.transaction() as connection:
        identity = sessions.identify(connection, settings, request.cookies)
        owner = sessions.require_owner(identity)
        upload = _owned_upload(connection, owner, upload_id)
    if upload["status"] != "awaiting_file":
        raise _invalid_state(upload["status"])

    size = _store(request).object_size(upload["incoming_key"])
    if size is None:
        # The client may still send it, as long as its URL lasts.
        raise ApiError(422, "object_missing")
    if size != upload["declared_size"]:
        with database.transaction() as connection:
            connection.execute(
                "UPDATE uploads SET status = 'rejected', rejection = 'size_mismatch', "
                "completed_at = now() WHERE id = %s AND status = 'awaiting_file'",
                (upload_id,),
            )
        raise ApiError(422, "size_mismatch")

    with database.transaction() as connection:
        # Only one of two simultaneous calls gets the row, and so queues the job.
        row = connection.execute(
            "UPDATE uploads SET status = 'uploaded', completed_at = now() "
            "WHERE id = %s AND status = 'awaiting_file' RETURNING id",
            (upload_id,),
        ).fetchone()
        if row is None:
            raise _invalid_state("uploaded")
        connection.execute(
            "INSERT INTO jobs (kind, payload) VALUES ('parse', %s)",
            (Jsonb({"upload_id": str(upload_id)}),),
        )
    return {"upload_id": str(upload_id), "status": "uploaded"}


@router.get("/uploads", response_model=models.UploadPage)
def list_uploads(
    connection: ConnectionDep,
    identity: IdentityDep,
    status: UploadStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=_LIST_MAX)] = 50,
    cursor: str | None = None,
) -> dict[str, Any]:
    """The owner's uploads, newest first."""
    owner = sessions.require_owner(identity)
    conditions = [owner.condition]
    if status is not None:
        conditions.append(sql.SQL("status = {}").format(sql.Literal(status)))
    if cursor is not None:
        created_at, row_id = pagination.decode(cursor)
        conditions.append(
            sql.SQL("(created_at, id) < ({}, {})").format(
                sql.Literal(created_at), sql.Literal(row_id)
            )
        )
    query = sql.SQL(
        "SELECT {} FROM uploads WHERE {} ORDER BY created_at DESC, id DESC LIMIT {}"
    ).format(_COLUMNS, sql.SQL(" AND ").join(conditions), sql.Literal(limit + 1))
    with connection.cursor(row_factory=dict_row) as rows:
        found = rows.execute(query).fetchall()
    page = found[:limit]
    more = len(found) > limit
    return {
        "items": [_item(row) for row in page],
        "next_cursor": pagination.encode(page[-1]["created_at"], page[-1]["id"]) if more else None,
    }


@router.get("/uploads/{upload_id}", response_model=models.Upload)
def get_upload(
    upload_id: uuid.UUID, connection: ConnectionDep, identity: IdentityDep
) -> dict[str, Any]:
    owner = sessions.require_owner(identity)
    query = sql.SQL("SELECT {} FROM uploads WHERE id = %s AND {}").format(_COLUMNS, owner.condition)
    with connection.cursor(row_factory=dict_row) as rows:
        row = rows.execute(query, (upload_id,)).fetchone()
    if row is None:
        raise not_found()
    return _item(row)
