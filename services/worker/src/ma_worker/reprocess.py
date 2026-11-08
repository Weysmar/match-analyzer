"""`ma-worker reprocess`: queues again the matches an older parser or analysis produced (section 5.2
of CLAUDE.md), optionally on a range of the game's `BuildID` only.

A match whose raw file was purged cannot be parsed again: it is reported, never queued. A match that
already waits for the same job is not queued twice.
"""

import subprocess
import uuid
from dataclasses import dataclass, field

from psycopg import sql

from ma_worker.queue import Connection
from ma_worker.settings import Settings
from rl_analysis import ANALYSIS_VERSION


@dataclass
class Summary:
    selected: list[uuid.UUID] = field(default_factory=list)
    purged: list[uuid.UUID] = field(default_factory=list)
    queued: int = 0
    already_waiting: int = 0


def parser_version(settings: Settings) -> str:
    """The version of the parser the worker runs, as `rl-parse --version` gives it."""
    output = subprocess.run(
        [settings.parser_bin, "--version"], capture_output=True, text=True, check=True, timeout=10
    ).stdout
    return output.split()[-1]


def _build_range(build_from: int | None, build_to: int | None) -> sql.Composable:
    conditions: list[sql.Composable] = []
    if build_from is not None:
        conditions.append(sql.SQL("build_id >= {}").format(sql.Literal(build_from)))
    if build_to is not None:
        conditions.append(sql.SQL("build_id <= {}").format(sql.Literal(build_to)))
    return sql.SQL(" AND ").join(conditions) if conditions else sql.SQL("true")


def _select(connection: Connection, condition: sql.Composable) -> list[tuple[uuid.UUID, bool]]:
    query = sql.SQL(
        "SELECT id, raw_key IS NULL OR raw_deleted_at IS NOT NULL FROM matches WHERE {} "
        "ORDER BY created_at"
    ).format(condition)
    return [(row[0], row[1]) for row in connection.execute(query).fetchall()]


def _queue(connection: Connection, kind: str, matches: list[uuid.UUID], summary: Summary) -> None:
    for match_id in matches:
        row = connection.execute(
            """
            INSERT INTO jobs (kind, payload)
            SELECT %(kind)s, jsonb_build_object('match_id', %(match)s::text)
            WHERE NOT EXISTS (
                SELECT FROM jobs
                WHERE kind = %(kind)s AND payload->>'match_id' = %(match)s::text
                    AND status IN ('queued', 'running')
            )
            RETURNING id
            """,
            {"kind": kind, "match": match_id},
        ).fetchone()
        if row is None:
            summary.already_waiting += 1
        else:
            summary.queued += 1


def parser_outdated(
    connection: Connection,
    version: str,
    *,
    build_from: int | None = None,
    build_to: int | None = None,
    dry_run: bool = False,
) -> Summary:
    """Matches parsed by another version of the parser: a `reparse` job each."""
    condition = sql.SQL("parser_version <> {} AND {}").format(
        sql.Literal(version), _build_range(build_from, build_to)
    )
    summary = Summary()
    for match_id, purged in _select(connection, condition):
        (summary.purged if purged else summary.selected).append(match_id)
    if not dry_run:
        _queue(connection, "reparse", summary.selected, summary)
    return summary


def analysis_outdated(
    connection: Connection,
    *,
    build_from: int | None = None,
    build_to: int | None = None,
    dry_run: bool = False,
) -> Summary:
    """Parsed matches never analyzed, or by another version of the analysis: an `analyze` job each.
    A `header_only` match has nothing to analyze."""
    condition = sql.SQL(
        "status IN ('parsed', 'ready') AND analysis_version IS DISTINCT FROM {} AND {}"
    ).format(sql.Literal(ANALYSIS_VERSION), _build_range(build_from, build_to))
    summary = Summary(selected=[match_id for match_id, _ in _select(connection, condition)])
    if not dry_run:
        _queue(connection, "analyze", summary.selected, summary)
    return summary


def report(summary: Summary, *, dry_run: bool) -> str:
    lines = [f"selected: {len(summary.selected)}"]
    if dry_run:
        lines.append("dry run: nothing queued")
    else:
        lines.append(f"queued: {summary.queued}, already waiting: {summary.already_waiting}")
    if summary.purged:
        lines.append(f"raw file purged, cannot be parsed again: {len(summary.purged)}")
        lines += [f"  {match_id}" for match_id in summary.purged]
    return "\n".join(lines)
