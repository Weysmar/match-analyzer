"""Choosing the outdated matches (T7.14), against PostgreSQL with the worker's own role."""

import uuid
from typing import Any

import pytest

from ma_db.testing import Connection, Factory
from ma_worker import reprocess
from rl_analysis import ANALYSIS_VERSION

pytestmark = pytest.mark.db

CURRENT = "0.1.2"


def match_with(conn: Connection, make: Factory, **columns: Any) -> uuid.UUID:
    match = make.match(columns.pop("status", "ready"))
    values = {"parser_version": CURRENT, "analysis_version": ANALYSIS_VERSION, "raw_key": "raw/x"}
    values |= columns
    for name, value in values.items():
        conn.execute(f"UPDATE matches SET {name} = %s WHERE id = %s".encode(), (value, match))
    return match


def queued(conn: Connection, kind: str) -> list[str]:
    rows = conn.execute(
        "SELECT payload->>'match_id' FROM jobs WHERE kind = %s ORDER BY id", (kind,)
    ).fetchall()
    return [row[0] for row in rows]


def test_only_matches_of_another_parser_are_parsed_again(
    conn: Connection, worker_conn: Connection, make: Factory
) -> None:
    old = match_with(conn, make, parser_version="0.1.1")
    match_with(conn, make)
    summary = reprocess.parser_outdated(worker_conn, CURRENT)
    assert summary.selected == [old]
    assert summary.queued == 1
    assert queued(conn, "reparse") == [str(old)]


def test_a_purged_raw_file_is_reported_not_queued(
    conn: Connection, worker_conn: Connection, make: Factory
) -> None:
    purged = match_with(conn, make, parser_version="0.1.1", raw_deleted_at="2026-11-01")
    no_raw = match_with(conn, make, parser_version="0.1.1", raw_key=None)
    summary = reprocess.parser_outdated(worker_conn, CURRENT)
    assert summary.selected == []
    assert set(summary.purged) == {purged, no_raw}
    assert queued(conn, "reparse") == []
    report = reprocess.report(summary, dry_run=False)
    assert "cannot be parsed again: 2" in report
    assert str(purged) in report


def test_a_range_of_builds(conn: Connection, worker_conn: Connection, make: Factory) -> None:
    before = match_with(conn, make, parser_version="0.1.1", build_id=100)
    inside = match_with(conn, make, parser_version="0.1.1", build_id=200)
    after = match_with(conn, make, parser_version="0.1.1", build_id=300)
    unknown = match_with(conn, make, parser_version="0.1.1", build_id=None)
    assert reprocess.parser_outdated(
        worker_conn, CURRENT, build_from=150, build_to=250
    ).selected == [inside]
    assert set(
        reprocess.parser_outdated(worker_conn, CURRENT, build_from=150, dry_run=True).selected
    ) == {
        inside,
        after,
    }
    assert set(
        reprocess.parser_outdated(worker_conn, CURRENT, build_to=250, dry_run=True).selected
    ) == {
        before,
        inside,
    }
    assert unknown in reprocess.parser_outdated(worker_conn, CURRENT, dry_run=True).selected


def test_a_dry_run_queues_nothing(conn: Connection, worker_conn: Connection, make: Factory) -> None:
    old = match_with(conn, make, parser_version="0.1.1")
    summary = reprocess.parser_outdated(worker_conn, CURRENT, dry_run=True)
    assert summary.selected == [old]
    assert queued(conn, "reparse") == []
    assert "nothing queued" in reprocess.report(summary, dry_run=True)


def test_a_match_already_waiting_is_not_queued_twice(
    conn: Connection, worker_conn: Connection, make: Factory
) -> None:
    old = match_with(conn, make, parser_version="0.1.1")
    reprocess.parser_outdated(worker_conn, CURRENT)
    summary = reprocess.parser_outdated(worker_conn, CURRENT)
    assert (summary.queued, summary.already_waiting) == (0, 1)
    assert queued(conn, "reparse") == [str(old)]


def test_a_finished_job_does_not_stop_a_new_one(
    conn: Connection, worker_conn: Connection, make: Factory
) -> None:
    match_with(conn, make, parser_version="0.1.1")
    reprocess.parser_outdated(worker_conn, CURRENT)
    conn.execute("UPDATE jobs SET status = 'done'")
    assert reprocess.parser_outdated(worker_conn, CURRENT).queued == 1


def test_only_matches_of_another_analysis_are_analyzed_again(
    conn: Connection, worker_conn: Connection, make: Factory
) -> None:
    old = match_with(conn, make, analysis_version="0")
    never = match_with(conn, make, status="parsed", analysis_version=None)
    match_with(conn, make)
    match_with(conn, make, status="header_only", analysis_version=None)
    summary = reprocess.analysis_outdated(worker_conn)
    assert set(summary.selected) == {old, never}
    assert set(queued(conn, "analyze")) == {str(old), str(never)}


def test_the_analysis_takes_a_range_of_builds_too(
    conn: Connection, worker_conn: Connection, make: Factory
) -> None:
    inside = match_with(conn, make, analysis_version="0", build_id=200)
    match_with(conn, make, analysis_version="0", build_id=300)
    assert reprocess.analysis_outdated(worker_conn, build_to=250, dry_run=True).selected == [inside]
