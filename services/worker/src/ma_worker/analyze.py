"""The `analyze` job: the metrics of a parsed match, per player and per team, written to the
database, and its 2D view, written to the object store (T12.1 of docs/PLAN-V2.md).

It can run again at any point, and as often as needed: each metric of each player or team is one
row, which a new run overwrites. A match is `ready` once its metrics are all there.
"""

import gzip
import json
import logging
import tempfile
import uuid
from pathlib import Path

from psycopg.types.json import Jsonb

from ma_schemas import InvalidDocumentError
from ma_worker.queue import Connection, Job
from ma_worker.runner import PermanentError
from ma_worker.settings import Settings
from ma_worker.store import ObjectStore
from rl_analysis import ANALYSIS_VERSION, clock, situations, view
from rl_analysis.frames import InvalidFramesError
from rl_analysis.match import load
from rl_analysis.registry import METRICS, TEAM_METRICS, compute, compute_teams

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


def _write_teams(
    connection: Connection, match_id: uuid.UUID, results: dict[int, dict[str, float | None]]
) -> int:
    """One row per team and metric, written over the previous run's. Returns how many."""
    rows = [
        (match_id, team, metric_id, value, ANALYSIS_VERSION)
        for team, values in results.items()
        for metric_id, value in values.items()
    ]
    with connection.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO team_match_metrics (match_id, team, metric_id, value, analysis_version)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (match_id, team, metric_id) DO UPDATE
            SET value = excluded.value, analysis_version = excluded.analysis_version,
                computed_at = now()
            """,
            rows,
        )
    connection.execute(
        "DELETE FROM team_match_metrics WHERE match_id = %s AND NOT metric_id = ANY(%s)",
        (match_id, [metric.id for metric in TEAM_METRICS]),
    )
    return len(rows)


def _write_situations(
    connection: Connection,
    match_id: uuid.UUID,
    found: list[situations.Situation] | None,
    ids: dict[int, int],
) -> int:
    """The match's situations, in place of the previous run's. Returns how many."""
    connection.execute("DELETE FROM match_situations WHERE match_id = %s", (match_id,))
    rows = [
        (
            match_id,
            situation.kind,
            situation.time_s,
            situation.clock_s,
            situation.team,
            [ids[player] for player in situation.players if player in ids],
            list(situation.tags),
            Jsonb(situations.with_ids(situation.details, ids)),
            ANALYSIS_VERSION,
        )
        for situation in found or []
    ]
    with connection.cursor() as cursor:
        cursor.executemany(
            "INSERT INTO match_situations (match_id, kind, time_s, game_time_s, team, player_ids, "
            "tags, details, analysis_version) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            rows,
        )
    return len(rows)


def view_key(match_id: uuid.UUID) -> str:
    return f"views/{match_id}.json.gz"


def _player_ids(connection: Connection, match_id: uuid.UUID) -> dict[int, int]:
    """`player_idx` to `match_player_id`, for the players found in the frames."""
    rows = connection.execute(
        "SELECT frames_idx, id FROM match_players WHERE match_id = %s AND frames_idx IS NOT NULL",
        (match_id,),
    ).fetchall()
    return dict(rows)


def _store_view(
    store: ObjectStore, match_id: uuid.UUID, document: dict[str, object], folder: Path
) -> str:
    """The view, compressed, over the previous one: the browser unpacks it itself."""
    path = folder / "view.json.gz"
    path.write_bytes(gzip.compress(json.dumps(document, separators=(",", ":")).encode()))
    key = view_key(match_id)
    store.upload(path, key, "application/gzip")
    return key


def _write_clock(
    connection: Connection, match_id: uuid.UUID, game_clock: clock.Clock, goal_frames: list[int]
) -> None:
    """The match's length and overtime, and the clock of each goal, found by its frame."""
    connection.execute(
        "UPDATE matches SET game_length_s = %s, overtime_from_s = %s WHERE id = %s",
        (game_clock.length_s, game_clock.overtime_from_s, match_id),
    )
    with connection.cursor() as cursor:
        cursor.executemany(
            "UPDATE match_events SET game_time_s = %s "
            "WHERE match_id = %s AND kind = 'goal' AND frame = %s",
            [
                (seconds, match_id, frame)
                for seconds, frame in zip(game_clock.goals_s, goal_frames, strict=True)
            ],
        )


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
        team_results = compute_teams(match)
        game_clock = clock.compute(match)
        ids = _player_ids(connection, match_id)
        found = situations.detect(match)
        # Files first: if the database then fails, the next run writes the same key again.
        stored_view = _store_view(store, match_id, view.build(match, ids), Path(folder))
    with connection.transaction():
        written = _write(connection, match_id, results)
        written += _write_teams(connection, match_id, team_results)
        written += _write_situations(connection, match_id, found, ids)
        _write_clock(
            connection, match_id, game_clock, [goal["frame"] for goal in match.events["goals"]]
        )
        connection.execute(
            "UPDATE matches SET status = 'ready', analysis_version = %s, analyzed_at = now(), "
            "view_key = %s WHERE id = %s",
            (ANALYSIS_VERSION, stored_view, match_id),
        )
    log.info("match %s analyzed: %d values, version %s", match_id, written, ANALYSIS_VERSION)
