"""Settings, and the store without a server. No database needed."""

from pathlib import Path

import pytest

from ma_worker.cli import build_handlers, parser, resolve_parser
from ma_worker.settings import Settings, SettingsError
from ma_worker.store import S3Store, StoreError

URL = "postgresql://x@localhost/x"


def test_defaults() -> None:
    settings = Settings.from_env({"WORKER_DATABASE_URL": URL})
    assert settings.parser_bin == "rl-parse"
    assert settings.parser_timeout_s == 30
    assert settings.parser_memory_mb == 512
    assert settings.parser_max_fps is None
    assert settings.concurrency == 1
    assert settings.job_timeout_s == 600


def test_values_come_from_the_environment() -> None:
    settings = Settings.from_env(
        {
            "WORKER_DATABASE_URL": URL,
            "S3_ENDPOINT": "http://store.test",
            "S3_BUCKET": "a-bucket",
            "PARSER_BIN": "/usr/local/bin/rl-parse",
            "PARSER_TIMEOUT_S": "20",
            "PARSER_MEMORY_MB": "256",
            "PARSER_MAX_FPS": "30",
            "WORKER_CONCURRENCY": "2",
            "WORKER_JOB_TIMEOUT_S": "300",
        }
    )
    assert settings.s3_endpoint == "http://store.test"
    assert settings.parser_bin == "/usr/local/bin/rl-parse"
    assert settings.parser_timeout_s == 20
    assert settings.parser_memory_mb == 256
    assert settings.parser_max_fps == 30
    assert settings.concurrency == 2
    assert settings.job_timeout_s == 300


def test_the_database_url_is_required() -> None:
    with pytest.raises(SettingsError, match="WORKER_DATABASE_URL"):
        Settings.from_env({})


@pytest.mark.parametrize("value", ["soon", "0", "-1"])
def test_invalid_numbers_are_refused(value: str) -> None:
    with pytest.raises(SettingsError, match="PARSER_TIMEOUT_S"):
        Settings.from_env({"WORKER_DATABASE_URL": URL, "PARSER_TIMEOUT_S": value})


def test_a_job_has_to_outlast_its_parser_runs() -> None:
    env = {"WORKER_DATABASE_URL": URL, "PARSER_TIMEOUT_S": "30", "WORKER_JOB_TIMEOUT_S": "60"}
    with pytest.raises(SettingsError, match="WORKER_JOB_TIMEOUT_S"):
        Settings.from_env(env)


def test_secrets_stay_out_of_the_settings_text() -> None:
    settings = Settings(
        database_url="postgresql://user:db-password@host/db", s3_secret_access_key="s3-secret"
    )
    assert "db-password" not in repr(settings)
    assert "s3-secret" not in repr(settings)


def test_no_store_configured_fails_cleanly() -> None:
    with pytest.raises(StoreError):
        S3Store(Settings(database_url="unused")).size("a-key")


def test_a_store_out_of_reach_fails_cleanly(tmp_path: Path) -> None:
    store = S3Store(
        Settings(
            database_url="unused",
            s3_endpoint="http://127.0.0.1:1",
            s3_region="us-east-1",
            s3_bucket="a-bucket",
            s3_access_key_id="a",
            s3_secret_access_key="b",
        )
    )
    source = tmp_path / "source.bin"
    source.write_bytes(b"x")
    target = tmp_path / "target.bin"
    with pytest.raises(StoreError):
        store.size("a-key")
    with pytest.raises(StoreError):
        store.upload(source, "a-key", "application/octet-stream")
    with pytest.raises(StoreError):
        store.download("a-key", target, 10)
    assert not target.exists()
    with pytest.raises(StoreError):
        store.copy("a-key", "other")
    with pytest.raises(StoreError):
        store.delete("a-key")


def test_the_parser_is_found_and_made_absolute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = tmp_path / "rl-parse"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    binary.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    resolved = resolve_parser(Settings(database_url="unused"))
    assert resolved.parser_bin == str(binary)


def test_a_missing_parser_stops_the_start(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(SettingsError, match="PARSER_BIN"):
        resolve_parser(Settings(database_url="unused"))


def test_every_job_of_v1_has_a_handler() -> None:
    handlers = set(build_handlers(Settings(database_url="unused")))
    assert handlers == {"parse", "analyze", "reparse", "gc_match"}


def test_retention_comes_from_the_environment() -> None:
    settings = Settings.from_env(
        {
            "WORKER_DATABASE_URL": "postgresql://unused",
            "RAW_RETENTION_DAYS": "7",
            "RAW_RETENTION_HEADER_ONLY_DAYS": "90",
            "PURGE_EVERY_S": "600",
        }
    )
    assert (settings.raw_retention_days, settings.raw_retention_header_only_days) == (7, 90)
    assert settings.purge_every_s == 600
    defaults = Settings.from_env({"WORKER_DATABASE_URL": "postgresql://unused"})
    assert (defaults.raw_retention_days, defaults.raw_retention_header_only_days) == (30, 180)


@pytest.mark.parametrize(
    "argv",
    [
        ["reprocess"],
        ["reprocess", "--parser-outdated", "--analysis-outdated"],
        ["reprocess", "--parser-outdated", "--build-from", "soon"],
        ["nothing"],
    ],
)
def test_the_command_line_refuses_what_makes_no_sense(argv: list[str]) -> None:
    with pytest.raises(SystemExit):
        parser().parse_args(argv)


def test_the_command_line_reads_a_reprocess() -> None:
    arguments = parser().parse_args(
        ["reprocess", "--parser-outdated", "--build-from", "100", "--build-to", "200", "--dry-run"]
    )
    assert arguments.parser_outdated
    assert (arguments.build_from, arguments.build_to, arguments.dry_run) == (100, 200, True)


def test_the_upload_limit_comes_from_the_environment() -> None:
    env = {"WORKER_DATABASE_URL": URL, "UPLOAD_MAX_BYTES": "10"}
    assert Settings.from_env(env).upload_max_bytes == 10
