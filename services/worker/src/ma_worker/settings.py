"""The worker's configuration, read once from the environment."""

import os
from collections.abc import Mapping
from dataclasses import dataclass, field


class SettingsError(ValueError):
    """The configuration cannot run."""


def _integer(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise SettingsError(f"{name} must be a whole number") from None
    if value < 1:
        raise SettingsError(f"{name} must be at least 1")
    return value


@dataclass(frozen=True)
class Settings:
    database_url: str = field(repr=False)
    s3_endpoint: str = ""
    s3_region: str = "auto"
    s3_bucket: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = field(default="", repr=False)
    parser_bin: str = "rl-parse"
    parser_timeout_s: int = 30
    parser_memory_mb: int = 512
    parser_max_fps: int | None = None
    concurrency: int = 1
    job_timeout_s: int = 600
    upload_max_bytes: int = 20_971_520
    # Section 11 of CLAUDE.md: raw replays go once derived data exists, header_only ones later.
    raw_retention_days: int = 30
    raw_retention_header_only_days: int = 180
    purge_every_s: int = 3600

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        values = os.environ if env is None else env
        database_url = values.get("WORKER_DATABASE_URL", "").strip()
        if not database_url:
            raise SettingsError("WORKER_DATABASE_URL is not set")
        settings = cls(
            database_url=database_url,
            s3_endpoint=values.get("S3_ENDPOINT", "").strip(),
            s3_region=values.get("S3_REGION", "auto").strip(),
            s3_bucket=values.get("S3_BUCKET", "").strip(),
            s3_access_key_id=values.get("S3_ACCESS_KEY_ID", "").strip(),
            s3_secret_access_key=values.get("S3_SECRET_ACCESS_KEY", "").strip(),
            parser_bin=values.get("PARSER_BIN", "rl-parse").strip() or "rl-parse",
            parser_timeout_s=_integer(values, "PARSER_TIMEOUT_S", 30),
            parser_memory_mb=_integer(values, "PARSER_MEMORY_MB", 512),
            parser_max_fps=(
                _integer(values, "PARSER_MAX_FPS", 1) if values.get("PARSER_MAX_FPS") else None
            ),
            concurrency=_integer(values, "WORKER_CONCURRENCY", 1),
            job_timeout_s=_integer(values, "WORKER_JOB_TIMEOUT_S", 600),
            upload_max_bytes=_integer(values, "UPLOAD_MAX_BYTES", 20_971_520),
            raw_retention_days=_integer(values, "RAW_RETENTION_DAYS", 30),
            raw_retention_header_only_days=_integer(values, "RAW_RETENTION_HEADER_ONLY_DAYS", 180),
            purge_every_s=_integer(values, "PURGE_EVERY_S", 3600),
        )
        # A job has to outlast both of its parser runs, or it would be taken for abandoned.
        if settings.job_timeout_s <= 2 * settings.parser_timeout_s:
            raise SettingsError("WORKER_JOB_TIMEOUT_S must exceed twice PARSER_TIMEOUT_S")
        return settings
