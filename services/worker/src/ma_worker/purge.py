"""What is kept no longer than needed (step 9, T9.8; section 11 of CLAUDE.md):

- a raw replay, 30 days after its match was parsed, once frames and events exist; a match read from
  its header only, or failed, keeps it 180 days, to be parsed again after a fix;
- a file never sent, a day after its upload was opened;
- an expired session without an account: its links go, and its matches to `gc_match`;
- expired account sessions, and rate-limit counters past their window.

Every step takes the time as a parameter, so tests move the clock rather than wait. Files go before
the rows that point to them: a failure leaves a row to try again, never an orphan file.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

import psycopg
from psycopg.types.json import Jsonb

from ma_worker.queue import Connection
from ma_worker.settings import Settings
from ma_worker.store import ObjectStore

log = logging.getLogger("ma_worker")

INCOMING_MAX_AGE = timedelta(days=1)
# Twice the longest window of a counter (a day): nothing still counting is removed.
COUNTER_MAX_AGE = timedelta(days=2)
_BATCH = 500
# Matches whose frames and events exist: the raw file has served its purpose.
_DERIVED = ("parsed", "analyzing", "ready")
# Matches that may be parsed again after a fix of the parser (D6).
_KEPT_FOR_REPARSE = ("header_only", "failed")


@dataclass(frozen=True)
class Report:
    raw_files: int = 0
    stale_uploads: int = 0
    anonymous_sessions: int = 0
    matches_queued: int = 0
    auth_sessions: int = 0
    counters: int = 0

    def __str__(self) -> str:
        return (
            f"raw files {self.raw_files}, stale uploads {self.stale_uploads}, "
            f"anonymous sessions {self.anonymous_sessions} ({self.matches_queued} matches to "
            f"erase), account sessions {self.auth_sessions}, counters {self.counters}"
        )


def raw_files(connection: Connection, store: ObjectStore, settings: Settings, now: datetime) -> int:
    derived_before = now - timedelta(days=settings.raw_retention_days)
    kept_before = now - timedelta(days=settings.raw_retention_header_only_days)
    rows = connection.execute(
        """
        SELECT id, raw_key FROM matches
        WHERE raw_key IS NOT NULL AND raw_deleted_at IS NULL
            AND ((status = ANY(%s) AND coalesce(parsed_at, created_at) < %s)
                OR (status = ANY(%s) AND coalesce(parsed_at, created_at) < %s))
        LIMIT %s
        """,
        (list(_DERIVED), derived_before, list(_KEPT_FOR_REPARSE), kept_before, _BATCH),
    ).fetchall()
    for match_id, key in rows:
        store.delete(key)
        connection.execute("UPDATE matches SET raw_deleted_at = %s WHERE id = %s", (now, match_id))
    return len(rows)


def stale_uploads(connection: Connection, store: ObjectStore, now: datetime) -> int:
    """Uploads opened but never sent: the browser closed, or the URL expired long ago."""
    rows = connection.execute(
        "SELECT id, incoming_key FROM uploads "
        "WHERE status = 'awaiting_file' AND created_at < %s LIMIT %s",
        (now - INCOMING_MAX_AGE, _BATCH),
    ).fetchall()
    for upload_id, key in rows:
        store.delete(key)
        connection.execute(
            "DELETE FROM uploads WHERE id = %s AND status = 'awaiting_file'", (upload_id,)
        )
    return len(rows)


def anonymous_sessions(connection: Connection, now: datetime) -> tuple[int, int]:
    """Expired sessions without an account, and how many matches they leave to `gc_match`."""
    sessions = 0
    queued = 0
    rows = connection.execute(
        "SELECT id FROM anonymous_sessions WHERE expires_at < %s LIMIT %s", (now, _BATCH)
    ).fetchall()
    for (session_id,) in rows:
        with connection.transaction():
            matches = [
                row[0]
                for row in connection.execute(
                    "SELECT match_id FROM user_matches WHERE anonymous_session_id = %s",
                    (session_id,),
                ).fetchall()
            ]
            # Its uploads, links and remembered players go along (ON DELETE CASCADE).
            connection.execute("DELETE FROM anonymous_sessions WHERE id = %s", (session_id,))
            with connection.cursor() as cursor:
                cursor.executemany(
                    "INSERT INTO jobs (kind, payload) VALUES ('gc_match', %s)",
                    [(Jsonb({"match_id": str(match_id)}),) for match_id in matches],
                )
        sessions += 1
        queued += len(matches)
    return sessions, queued


def auth_sessions(connection: Connection, now: datetime) -> int:
    cursor = connection.execute("DELETE FROM auth_sessions WHERE expires_at < %s", (now,))
    return cursor.rowcount


def counters(connection: Connection, now: datetime) -> int:
    cursor = connection.execute(
        "DELETE FROM rate_limit_buckets WHERE window_start < %s", (now - COUNTER_MAX_AGE,)
    )
    return cursor.rowcount


def _step[T](name: str, step: Callable[[], T], nothing: T) -> T:
    """A step that fails leaves the others to run: a store down must not keep sessions alive.
    The next pass tries again. Logs name the error's type only, never its text."""
    try:
        return step()
    except psycopg.OperationalError:
        raise
    except Exception as error:
        log.warning("purge: %s failed: %s", name, type(error).__name__)
        return nothing


def run(connection: Connection, store: ObjectStore, settings: Settings, now: datetime) -> Report:
    """One pass of every step."""
    sessions, queued = _step("sessions", lambda: anonymous_sessions(connection, now), (0, 0))
    report = Report(
        raw_files=_step("raw", lambda: raw_files(connection, store, settings, now), 0),
        stale_uploads=_step("uploads", lambda: stale_uploads(connection, store, now), 0),
        anonymous_sessions=sessions,
        matches_queued=queued,
        auth_sessions=_step("auth", lambda: auth_sessions(connection, now), 0),
        counters=_step("counters", lambda: counters(connection, now), 0),
    )
    log.info("purge: %s", report)
    return report
