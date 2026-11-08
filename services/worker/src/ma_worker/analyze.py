"""The `analyze` job: the V1 metrics of a parsed match, written to the database.

It can run again at any point, and as often as needed: each metric of each player is one row, which
a new run overwrites. A match is `ready` once its metrics are all there.
"""

import logging
import tempfile
import uuid
from pathlib import Path

from ma_schemas import InvalidDocumentError
from ma_worker.queue import Connection, Job
from ma_worker.runner import PermanentError
from ma_worker.settings import Settings
from ma_worker.store import ObjectStore
from rl_analysis import ANALYSIS_VERSION
from rl_analysis.frames import InvalidFramesError
from rl_analysis.match import load
from rl_analysis.registry import METRICS, compute

log = logging.getLogger("ma_worker")

# Frames run to a few megabytes (3.44 at most on the corpus): this only stops a runaway file.
_FILE_MAX_BYTES = 536_870_912
_ANALYZABLE = ("parsed", "ready")


def _write(
    connection: Connection,
    match_id: uuid.UUID,
    results: dict[int, dict[str, float | None]],
) -> int:
    """One row per player and metric, written over the previous run's. Returns how many."""
    players = connection.execute(
        "SELECT id, frames_idx FROM match_players WHERE match_id = %s AND frames_idx IS NOT NULL",
        (match_id,),
    ).fetchall()
    rows = [
        (player_id, metric_id, value, ANALYSIS_VERSION)
        for player_id, frames_idx in players
        for metric_id, value in results.get(frames_idx, {}).items()
    ]
    with connection.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO player_match_metrics (match_player_id, metric_id, value, analysis_version)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (match_player_id, metric_id) DO UPDATE
            SET value = excluded.value, analysis_version = excluded.analysis_version,
                computed_at = now()
            """,
            rows,
        )
    # A metric that no longer exists would linger, with an old version, next to the new ones.
    connection.execute(
        """
        DELETE FROM player_match_metrics metric
        USING match_players player
        WHERE player.id = metric.match_player_id AND player.match_id = %s
            AND NOT metric.metric_id = ANY(%s)
        """,
        (match_id, [metric.id for metric in METRICS]),
    )
    return len(rows)


def handle(connection: Connection, job: Job, store: ObjectStore, settings: Settings) -> None:
    try:
        match_id = uuid.UUID(job.payload["match_id"])
    except KeyError, ValueError, TypeError, AttributeError:
        raise PermanentError("bad_payload") from None
    row = connection.execute(
        "SELECT status, frames_key, events_key FROM matches WHERE id = %s", (match_id,)
    ).fetchone()
    if row is None or row[0] not in _ANALYZABLE or row[1] is None or row[2] is None:
        # Erased meanwhile, or header_only: nothing to compute from.
        return
    _, frames_key, events_key = row
    with tempfile.TemporaryDirectory(prefix="ma-analyze-") as folder:
        frames_path, events_path = Path(folder) / "frames.parquet", Path(folder) / "events.json"
        store.download(frames_key, frames_path, _FILE_MAX_BYTES)
        store.download(events_key, events_path, _FILE_MAX_BYTES)
        try:
            match = load(frames_path, events_path)
        except InvalidFramesError, InvalidDocumentError, ValueError:
            # Written by the parser: a mismatch means a bug or a schema change, not a bad file.
            raise PermanentError("invalid_parsed_files") from None
        results = compute(match)
    with connection.transaction():
        written = _write(connection, match_id, results)
        connection.execute(
            "UPDATE matches SET status = 'ready', analysis_version = %s, analyzed_at = now() "
            "WHERE id = %s",
            (ANALYSIS_VERSION, match_id),
        )
    log.info("match %s analyzed: %d values, version %s", match_id, written, ANALYSIS_VERSION)
