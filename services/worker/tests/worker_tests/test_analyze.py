"""The `analyze` job, against PostgreSQL with the worker's own role, on frames made by hand."""

import json
import logging
import uuid
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from ma_db.testing import Connection, Factory, count
from ma_schemas import frames_columns
from ma_worker import analyze
from ma_worker.queue import Job
from ma_worker.runner import PermanentError
from ma_worker.settings import Settings
from rl_analysis import ANALYSIS_VERSION
from rl_analysis.registry import METRICS, TEAM_METRICS

from .helpers import MemoryStore, events, member

pytestmark = pytest.mark.db

_POLARS = {"uint32": pl.UInt32, "uint8": pl.UInt8, "float32": pl.Float32, "boolean": pl.Boolean}
SETTINGS = Settings(database_url="unused")


def frame_rows(player: int, team: int, boost: float, seconds: int) -> list[dict[str, Any]]:
    """One player in live play, 1 s per frame, at a constant boost."""
    return [
        {
            "frame": index,
            "time_s": float(index),
            "dt_s": 1.0,
            "phase": 3,
            "ball_x": 0.0,
            "ball_y": 0.0,
            "ball_z": 92.75,
            "ball_vx": 0.0,
            "ball_vy": 0.0,
            "ball_vz": 0.0,
            "player_idx": player,
            "team": team,
            "present": True,
            "x": 0.0,
            "y": -1000.0 if team == 0 else 1000.0,
            "z": 17.0,
            "qx": 0.0,
            "qy": 0.0,
            "qz": 0.0,
            "qw": 1.0,
            "vx": 1000.0,
            "vy": 0.0,
            "vz": 0.0,
            "boost": boost,
            "boost_active": False,
            "jumped": False,
            "double_jumped": False,
            "dodged": False,
            "demolished": False,
        }
        for index in range(seconds)
    ]


@pytest.fixture
def store() -> MemoryStore:
    return MemoryStore()


def parsed_match(
    conn: Connection, make: Factory, store: MemoryStore, tmp_path: Path, *, status: str = "parsed"
) -> tuple[uuid.UUID, int, int]:
    """A parsed match of two players whose files are in the store."""
    match = make.match(status)
    blue = make.player(match, team=0)
    orange = make.player(match, team=1)
    conn.execute("UPDATE match_players SET frames_idx = 0 WHERE id = %s", (blue,))
    conn.execute("UPDATE match_players SET frames_idx = 1 WHERE id = %s", (orange,))
    frames = pl.DataFrame(
        frame_rows(0, 0, 40.0, 10) + frame_rows(1, 1, 80.0, 10),
        schema={name: _POLARS[kind] for name, kind in frames_columns().items()},
    )
    path = tmp_path / "frames.parquet"
    frames.write_parquet(path)
    frames_key, events_key = f"frames/{match}.parquet", f"events/{match}.json"
    store.objects[frames_key] = path.read_bytes()
    document = events(
        roster=[member(0, "Blue", 0, "steam", "1"), member(1, "Orange", 1, "epic", "a")],
        goals=[],
        demolitions=[],
    )
    store.objects[events_key] = json.dumps(document).encode()
    conn.execute(
        "UPDATE matches SET frames_key = %s, events_key = %s WHERE id = %s",
        (frames_key, events_key, match),
    )
    return match, blue, orange


def run_job(worker_conn: Connection, store: MemoryStore, match: uuid.UUID) -> None:
    analyze.handle(worker_conn, Job(1, "analyze", {"match_id": str(match)}, 1, 3), store, SETTINGS)


def metrics_of(conn: Connection, player: int) -> dict[str, Any]:
    rows = conn.execute(
        "SELECT metric_id, value, analysis_version FROM player_match_metrics "
        "WHERE match_player_id = %s",
        (player,),
    ).fetchall()
    return {metric_id: (value, version) for metric_id, value, version in rows}


def test_a_parsed_match_becomes_ready(
    conn: Connection, worker_conn: Connection, make: Factory, store: MemoryStore, tmp_path: Path
) -> None:
    match, blue, orange = parsed_match(conn, make, store, tmp_path)
    run_job(worker_conn, store, match)
    row = conn.execute(
        "SELECT status, analysis_version, analyzed_at IS NOT NULL FROM matches WHERE id = %s",
        (match,),
    ).fetchone()
    assert row == ("ready", ANALYSIS_VERSION, True)
    blue_metrics = metrics_of(conn, blue)
    assert set(blue_metrics) == {metric.id for metric in METRICS}
    assert blue_metrics["boost.avg"] == (pytest.approx(40.0), ANALYSIS_VERSION)
    assert metrics_of(conn, orange)["boost.avg"][0] == pytest.approx(80.0)
    assert metrics_of(conn, orange)["move.speed_avg"][0] == pytest.approx(1000.0)


def team_metrics_of(conn: Connection, match: uuid.UUID) -> dict[tuple[int, str], Any]:
    rows = conn.execute(
        "SELECT team, metric_id, value, analysis_version FROM team_match_metrics "
        "WHERE match_id = %s",
        (match,),
    ).fetchall()
    return {(team, metric_id): (value, version) for team, metric_id, value, version in rows}


def test_both_teams_get_every_team_metric(
    conn: Connection, worker_conn: Connection, make: Factory, store: MemoryStore, tmp_path: Path
) -> None:
    """Without detected touches, possession is unknown: stored, as null."""
    match, _, _ = parsed_match(conn, make, store, tmp_path)
    run_job(worker_conn, store, match)
    assert team_metrics_of(conn, match) == {
        (team, metric.id): (None, ANALYSIS_VERSION) for team in (0, 1) for metric in TEAM_METRICS
    }


def test_a_new_run_adds_no_team_row_and_drops_a_retired_one(
    conn: Connection, worker_conn: Connection, make: Factory, store: MemoryStore, tmp_path: Path
) -> None:
    match, _, _ = parsed_match(conn, make, store, tmp_path)
    run_job(worker_conn, store, match)
    make.team_metric(match, 0, "poss.retired")
    run_job(worker_conn, store, match)
    assert set(team_metrics_of(conn, match)) == {
        (team, metric.id) for team in (0, 1) for metric in TEAM_METRICS
    }


def test_files_of_an_older_parser_give_null_v2_metrics(
    conn: Connection, worker_conn: Connection, make: Factory, store: MemoryStore, tmp_path: Path
) -> None:
    """A purged match keeps the events.json of its parser (version 1, T11.8): its V1 metrics
    come back, what that parser did not detect stays unknown."""
    match, blue, _ = parsed_match(conn, make, store, tmp_path)
    events_key = f"events/{match}.json"
    document = json.loads(store.objects[events_key])
    for name in ("touches", "kickoffs", "fifty_fifties", "beaten_to_ball"):
        del document[name]
    document |= {"schema_version": 1, "parser_version": "0.1.2"}
    store.objects[events_key] = json.dumps(document).encode()
    run_job(worker_conn, store, match)
    values = {metric_id: value for metric_id, (value, _) in metrics_of(conn, blue).items()}
    assert values["boost.avg"] == pytest.approx(40.0)
    v2 = [metric_id for metric_id in values if metric_id.startswith(("touch.", "poss."))]
    assert v2
    assert all(values[metric_id] is None for metric_id in v2)
    assert all(value is None for value, _ in team_metrics_of(conn, match).values())


def test_a_new_run_adds_no_row(
    conn: Connection, worker_conn: Connection, make: Factory, store: MemoryStore, tmp_path: Path
) -> None:
    match, blue, _ = parsed_match(conn, make, store, tmp_path)
    run_job(worker_conn, store, match)
    before = count(conn, "SELECT count(*) FROM player_match_metrics")
    conn.execute(
        "UPDATE player_match_metrics SET value = -1, analysis_version = 'old' "
        "WHERE match_player_id = %s",
        (blue,),
    )
    run_job(worker_conn, store, match)
    assert count(conn, "SELECT count(*) FROM player_match_metrics") == before
    assert metrics_of(conn, blue)["boost.avg"] == (pytest.approx(40.0), ANALYSIS_VERSION)


def test_a_metric_that_no_longer_exists_goes_away(
    conn: Connection, worker_conn: Connection, make: Factory, store: MemoryStore, tmp_path: Path
) -> None:
    match, blue, _ = parsed_match(conn, make, store, tmp_path)
    make.metric(blue, "boost.retired", 1.0)
    run_job(worker_conn, store, match)
    assert "boost.retired" not in metrics_of(conn, blue)


def test_a_player_without_frames_gets_no_metric(
    conn: Connection, worker_conn: Connection, make: Factory, store: MemoryStore, tmp_path: Path
) -> None:
    match, _, _ = parsed_match(conn, make, store, tmp_path)
    left_early = make.player(match, team=1)
    run_job(worker_conn, store, match)
    assert metrics_of(conn, left_early) == {}


def test_an_undefined_value_is_stored_as_null(
    conn: Connection, worker_conn: Connection, make: Factory, store: MemoryStore, tmp_path: Path
) -> None:
    """1v1: the last back means nothing for a player alone in their team."""
    match, blue, _ = parsed_match(conn, make, store, tmp_path)
    run_job(worker_conn, store, match)
    assert metrics_of(conn, blue)["pos.pct_last_back"] == (None, ANALYSIS_VERSION)


@pytest.mark.parametrize("status", ["header_only", "pending", "failed"])
def test_a_match_without_frames_is_left_alone(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    tmp_path: Path,
    status: str,
) -> None:
    match, _, _ = parsed_match(conn, make, store, tmp_path, status=status)
    run_job(worker_conn, store, match)
    assert conn.execute("SELECT status FROM matches WHERE id = %s", (match,)).fetchone() == (
        status,
    )
    assert count(conn, "SELECT count(*) FROM player_match_metrics") == 0


def test_a_match_erased_meanwhile_is_fine(worker_conn: Connection, store: MemoryStore) -> None:
    run_job(worker_conn, store, uuid.uuid4())


def test_a_ready_match_can_be_analyzed_again(
    conn: Connection, worker_conn: Connection, make: Factory, store: MemoryStore, tmp_path: Path
) -> None:
    match, blue, _ = parsed_match(conn, make, store, tmp_path, status="ready")
    run_job(worker_conn, store, match)
    assert metrics_of(conn, blue)["boost.avg"][0] == pytest.approx(40.0)


def test_files_off_their_schema_stop_the_job(
    conn: Connection, worker_conn: Connection, make: Factory, store: MemoryStore, tmp_path: Path
) -> None:
    match, _, _ = parsed_match(conn, make, store, tmp_path)
    store.objects[f"events/{match}.json"] = b'{"schema_version": 1}'
    with pytest.raises(PermanentError) as failure:
        run_job(worker_conn, store, match)
    assert failure.value.code == "invalid_parsed_files"
    assert conn.execute("SELECT status FROM matches WHERE id = %s", (match,)).fetchone() == (
        "parsed",
    )


@pytest.mark.parametrize("payload", [{}, {"match_id": "nope"}, {"match_id": 3}])
def test_a_bad_payload_stops_the_job(
    worker_conn: Connection, store: MemoryStore, payload: dict[str, Any]
) -> None:
    with pytest.raises(PermanentError) as failure:
        analyze.handle(worker_conn, Job(1, "analyze", payload, 1, 3), store, SETTINGS)
    assert failure.value.code == "bad_payload"


def test_nothing_personal_reaches_the_log(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    match, _, _ = parsed_match(conn, make, store, tmp_path)
    with caplog.at_level(logging.INFO, logger="ma_worker"):
        run_job(worker_conn, store, match)
    assert "analyzed" in caplog.text
    for secret in ("Blue", "Orange"):
        assert secret not in caplog.text


def test_the_game_clock_is_written(
    conn: Connection, worker_conn: Connection, make: Factory, store: MemoryStore, tmp_path: Path
) -> None:
    """The match's length, no overtime, and each goal's clock, found by its frame (A63)."""
    match, blue, _ = parsed_match(conn, make, store, tmp_path)
    document = json.loads(store.objects[f"events/{match}.json"])
    document["goals"] = [
        {"frame": 4, "time_s": 4.0, "team": 0, "player_idx": 0, "score_blue": 1, "score_orange": 0}
    ]
    store.objects[f"events/{match}.json"] = json.dumps(document).encode()
    conn.execute(
        "INSERT INTO match_events (match_id, kind, frame, time_s, team, actor_player_id) "
        "VALUES (%s, 'goal', 4, 4.0, 0, %s)",
        (match, blue),
    )
    run_job(worker_conn, store, match)
    assert conn.execute(
        "SELECT game_length_s, overtime_from_s FROM matches WHERE id = %s", (match,)
    ).fetchone() == (pytest.approx(10.0), None)
    # Frame 4 ends the fifth second of play.
    assert conn.execute(
        "SELECT game_time_s FROM match_events WHERE match_id = %s", (match,)
    ).fetchone() == (pytest.approx(5.0),)
