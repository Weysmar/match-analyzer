"""Backups of the database (T9.7 of docs/PLAN.md): `pg_dump` in its custom format, sent to a bucket
of their own, the latest `BACKUP_KEEP` kept; and the restore into an empty database.

The backups bucket is not the application's: its own token, its own lifecycle, out of the API's
and the worker's reach. A dump holds what the database holds, other players' names among it
(section 11 of CLAUDE.md): the bucket stays private, in the EU like the rest.

The password never goes on a command line: `pg_dump` and `pg_restore` get the connection through
libpq's environment variables.
"""

import logging
import os
import subprocess
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import boto3
import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

from ma_db.migrate import ROLES

PREFIX = "postgres/"
SUFFIX = ".dump"

log = logging.getLogger("ma_db.backup")


class BackupError(RuntimeError):
    """A backup or a restore that cannot go on. The message names no secret."""


@dataclass(frozen=True)
class Settings:
    endpoint: str
    region: str
    bucket: str
    access_key_id: str
    secret_access_key: str
    keep: int


def settings_from(values: Mapping[str, str]) -> Settings:
    """`BACKUP_S3_*`, falling back on the application's endpoint and region, never on its bucket
    nor its keys."""

    def value(name: str, fallback: str = "") -> str:
        return (values.get(name) or fallback).strip()

    settings = Settings(
        endpoint=value("BACKUP_S3_ENDPOINT", values.get("S3_ENDPOINT", "")),
        region=value("BACKUP_S3_REGION", values.get("S3_REGION", "")) or "auto",
        bucket=value("BACKUP_S3_BUCKET"),
        access_key_id=value("BACKUP_S3_ACCESS_KEY_ID"),
        secret_access_key=value("BACKUP_S3_SECRET_ACCESS_KEY"),
        keep=int(value("BACKUP_KEEP", "14")),
    )
    missing = [
        name
        for name, given in (
            ("BACKUP_S3_ENDPOINT", settings.endpoint),
            ("BACKUP_S3_BUCKET", settings.bucket),
            ("BACKUP_S3_ACCESS_KEY_ID", settings.access_key_id),
            ("BACKUP_S3_SECRET_ACCESS_KEY", settings.secret_access_key),
        )
        if not given
    ]
    if missing:
        raise BackupError(f"not set: {', '.join(missing)}")
    if settings.keep < 1:
        raise BackupError("BACKUP_KEEP must be at least 1")
    return settings


class Store(Protocol):
    def put(self, key: str, path: Path) -> None: ...
    def get(self, key: str, path: Path) -> None: ...
    def keys(self, prefix: str) -> list[str]: ...
    def delete(self, key: str) -> None: ...


class S3Store:
    """The backups bucket, through boto3."""

    def __init__(self, settings: Settings) -> None:
        self._bucket = settings.bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.endpoint,
            region_name=settings.region,
            aws_access_key_id=settings.access_key_id,
            aws_secret_access_key=settings.secret_access_key,
        )

    def put(self, key: str, path: Path) -> None:
        self._client.upload_file(str(path), self._bucket, key)

    def get(self, key: str, path: Path) -> None:
        self._client.download_file(self._bucket, key, str(path))

    def keys(self, prefix: str) -> list[str]:
        found: list[str] = []
        pages = self._client.get_paginator("list_objects_v2")
        for page in pages.paginate(Bucket=self._bucket, Prefix=prefix):
            found += [str(item["Key"]) for item in page.get("Contents", [])]
        return found

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=key)


def key_for(now: datetime) -> str:
    """Named by its UTC time, so that the names sort like the times."""
    return f"{PREFIX}{now.astimezone(UTC):%Y-%m-%dT%H%M%SZ}{SUFFIX}"


def backups(store: Store) -> list[str]:
    """Every backup in the bucket, oldest first."""
    return sorted(key for key in store.keys(PREFIX) if key.endswith(SUFFIX))


def to_prune(keys: list[str], keep: int) -> list[str]:
    """The backups beyond the latest `keep`, oldest first."""
    ordered = sorted(keys)
    return ordered[: max(0, len(ordered) - keep)]


def libpq_environment(url: str) -> dict[str, str]:
    """The connection as libpq's variables, for `pg_dump` and `pg_restore`: nothing else of the
    process's environment goes to them."""
    parts = conninfo_to_dict(url)
    names = {
        "host": "PGHOST",
        "port": "PGPORT",
        "user": "PGUSER",
        "password": "PGPASSWORD",
        "dbname": "PGDATABASE",
        "sslmode": "PGSSLMODE",
    }
    environment = {names[key]: str(value) for key, value in parts.items() if key in names and value}
    return {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), **environment}


def _run(command: list[str], url: str) -> None:
    result = subprocess.run(
        command, env=libpq_environment(url), capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        # pg_dump's and pg_restore's own words: they name objects, never the password.
        raise BackupError(f"{command[0]} failed: {result.stderr.strip()[-500:]}")


def backup(url: str, settings: Settings, store: Store, now: datetime) -> str:
    """One backup: the dump, its upload, then the oldest beyond `keep` deleted. Returns its key."""
    key = key_for(now)
    with tempfile.TemporaryDirectory(prefix="ma-backup-") as folder:
        path = Path(folder) / "database.dump"
        _run(["pg_dump", "--format=custom", "--no-password", f"--file={path}"], url)
        store.put(key, path)
    for old in to_prune(backups(store), settings.keep):
        store.delete(old)
    return key


def run(url: str, settings: Settings, store: Store, every_s: float) -> None:
    """The backup service: one backup at once, then one every `every_s` seconds. A failed backup
    is logged and the next one tried: the service stays up."""
    while True:
        try:
            key = backup(url, settings, store, datetime.now(UTC))
            log.info("backup written: %s", key)
        except Exception as error:
            log.error("backup failed: %s", error)
        time.sleep(every_s)


def _is_empty(url: str) -> bool:
    with psycopg.connect(url) as connection:
        row = connection.execute(
            "SELECT count(*) FROM pg_tables WHERE schemaname NOT IN ('pg_catalog', "
            "'information_schema')"
        ).fetchone()
    return row is not None and row[0] == 0


def _ensure_roles(url: str) -> None:
    """A blank instance has none of the roles the dump grants rights to: they are created without a
    password, which the next `ma-db upgrade` sets."""
    with psycopg.connect(url, autocommit=True) as connection:
        for role in ROLES:
            exists = connection.execute(
                "SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)
            ).fetchone()
            if exists is None:
                connection.execute(sql.SQL("CREATE ROLE {} LOGIN").format(sql.Identifier(role)))


def restore(name: str, into_url: str, store: Store) -> str:
    """Restores a backup (`latest`, or its key) into the database at `into_url`, which must be
    empty: a restore never writes over data. Returns the key restored."""
    found = backups(store)
    key = (found[-1] if found else "") if name == "latest" else name
    if key not in found:
        raise BackupError("no such backup" if name != "latest" else "no backup yet")
    if not _is_empty(into_url):
        raise BackupError("the target database is not empty: restore into a new one")
    _ensure_roles(into_url)
    with tempfile.TemporaryDirectory(prefix="ma-restore-") as folder:
        path = Path(folder) / "database.dump"
        store.get(key, path)
        _run(
            [
                "pg_restore",
                "--no-password",
                "--no-owner",
                "--exit-on-error",
                "--single-transaction",
                f"--dbname={conninfo_to_dict(into_url).get('dbname', '')}",
                str(path),
            ],
            into_url,
        )
    return key
