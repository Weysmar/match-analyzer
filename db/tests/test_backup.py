"""Backups (T9.7), without a database nor a bucket: a store in memory and `pg_dump` stood in for.
The real round trip, dump then restore into a blank database, runs in the production stack's check
(scripts/check-production-stack.sh)."""

import subprocess
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from ma_db import backup

URL = "postgresql://ma_owner:s3cret-owner@db:5432/match_analyzer"
ENV = {
    "S3_ENDPOINT": "https://account.r2.cloudflarestorage.com",
    "S3_BUCKET": "the-application-bucket",
    "S3_ACCESS_KEY_ID": "application-key",
    "S3_SECRET_ACCESS_KEY": "application-secret",
    "BACKUP_S3_BUCKET": "match-analyzer-backups",
    "BACKUP_S3_ACCESS_KEY_ID": "backup-key",
    "BACKUP_S3_SECRET_ACCESS_KEY": "backup-secret",
}


class MemoryStore:
    def __init__(self, keys: list[str] | None = None) -> None:
        self.objects: dict[str, bytes] = dict.fromkeys(keys or [], b"old")

    def put(self, key: str, path: Path) -> None:
        self.objects[key] = path.read_bytes()

    def get(self, key: str, path: Path) -> None:
        path.write_bytes(self.objects[key])

    def keys(self, prefix: str) -> list[str]:
        return [key for key in self.objects if key.startswith(prefix)]

    def delete(self, key: str) -> None:
        del self.objects[key]


def test_the_settings_never_borrow_the_applications_bucket_nor_keys() -> None:
    settings = backup.settings_from(ENV)
    assert settings.endpoint == ENV["S3_ENDPOINT"]
    assert settings.region == "auto"
    assert (settings.bucket, settings.access_key_id) == ("match-analyzer-backups", "backup-key")
    assert settings.keep == 14
    with pytest.raises(backup.BackupError, match="BACKUP_S3_BUCKET, BACKUP_S3_ACCESS_KEY_ID"):
        backup.settings_from({key: ENV[key] for key in ENV if not key.startswith("BACKUP_")})
    with pytest.raises(backup.BackupError, match="at least 1"):
        backup.settings_from({**ENV, "BACKUP_KEEP": "0"})


def test_names_sort_like_times_in_utc() -> None:
    paris = timezone(timedelta(hours=1))
    first = backup.key_for(datetime(2026, 11, 12, 23, 30, tzinfo=paris))
    second = backup.key_for(datetime(2026, 11, 12, 23, 0, tzinfo=UTC))
    assert first == "postgres/2026-11-12T223000Z.dump"
    assert sorted([second, first]) == [first, second]


def test_the_oldest_beyond_keep_are_pruned() -> None:
    keys = [f"postgres/2026-11-{day:02d}T000000Z.dump" for day in (3, 1, 2, 4)]
    assert backup.to_prune(keys, 2) == [
        "postgres/2026-11-01T000000Z.dump",
        "postgres/2026-11-02T000000Z.dump",
    ]
    assert backup.to_prune(keys, 10) == []


def test_the_password_goes_through_the_environment_only() -> None:
    environment = backup.libpq_environment(URL)
    assert environment["PGPASSWORD"] == "s3cret-owner"
    assert (environment["PGHOST"], environment["PGPORT"]) == ("db", "5432")
    assert (environment["PGUSER"], environment["PGDATABASE"]) == ("ma_owner", "match_analyzer")
    assert set(environment) == {"PATH", "PGHOST", "PGPORT", "PGUSER", "PGPASSWORD", "PGDATABASE"}


def stand_in(calls: list[dict[str, Any]], returncode: int = 0, stderr: str = "") -> Any:
    def run(command: list[str], **options: Any) -> subprocess.CompletedProcess[str]:
        calls.append({"command": command, **options})
        for argument in command:
            if argument.startswith("--file="):
                Path(argument.removeprefix("--file=")).write_bytes(b"PGDMP dump")
        return subprocess.CompletedProcess(command, returncode, "", stderr)

    return run


def test_a_backup_is_dumped_uploaded_then_the_oldest_pruned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(subprocess, "run", stand_in(calls))
    store = MemoryStore(
        ["postgres/2026-11-01T000000Z.dump", "postgres/2026-11-02T000000Z.dump", "other/keep.txt"]
    )
    settings = backup.settings_from({**ENV, "BACKUP_KEEP": "2"})
    key = backup.backup(URL, settings, store, datetime(2026, 11, 3, tzinfo=UTC))

    assert key == "postgres/2026-11-03T000000Z.dump"
    assert store.objects[key] == b"PGDMP dump"
    assert sorted(store.objects) == [
        "other/keep.txt",
        "postgres/2026-11-02T000000Z.dump",
        "postgres/2026-11-03T000000Z.dump",
    ]
    [call] = calls
    assert call["command"][:3] == ["pg_dump", "--format=custom", "--no-password"]
    assert "s3cret-owner" not in " ".join(call["command"])
    assert call["env"]["PGPASSWORD"] == "s3cret-owner"


def test_a_failed_dump_says_so_and_uploads_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(subprocess, "run", stand_in(calls, 1, "pg_dump: error: connection refused"))
    store = MemoryStore()
    with pytest.raises(backup.BackupError, match="pg_dump failed: pg_dump: error: connection"):
        backup.backup(URL, backup.settings_from(ENV), store, datetime(2026, 11, 3, tzinfo=UTC))
    assert store.objects == {}


def test_a_restore_takes_the_latest_into_an_empty_database_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(subprocess, "run", stand_in(calls))
    monkeypatch.setattr(backup, "_ensure_roles", lambda _url: None)
    empty = {"value": True}
    monkeypatch.setattr(backup, "_is_empty", lambda _url: empty["value"])
    store = MemoryStore(["postgres/2026-11-01T000000Z.dump", "postgres/2026-11-02T000000Z.dump"])
    target = "postgresql://ma_owner:s3cret-owner@db:5432/restore_check"

    assert backup.restore("latest", target, store) == "postgres/2026-11-02T000000Z.dump"
    [call] = calls
    assert call["command"][0] == "pg_restore"
    assert {"--no-owner", "--exit-on-error", "--single-transaction"} <= set(call["command"])
    assert "--dbname=restore_check" in call["command"]
    assert "s3cret-owner" not in " ".join(call["command"])

    with pytest.raises(backup.BackupError, match="no such backup"):
        backup.restore("postgres/1999-01-01T000000Z.dump", target, store)
    empty["value"] = False
    with pytest.raises(backup.BackupError, match="not empty"):
        backup.restore("latest", target, store)
    with pytest.raises(backup.BackupError, match="no backup yet"):
        backup.restore("latest", target, MemoryStore())
