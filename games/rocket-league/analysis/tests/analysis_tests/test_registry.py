"""Every metric is defined and named once."""

from pathlib import Path

import pytest

from rl_analysis.match import load
from rl_analysis.registry import METRICS, TEAM_METRICS, Metric, TeamMetric, compute, compute_teams

from .synthetic import frames, match_of, pickup, row


def test_ids_are_unique() -> None:
    ids = [metric.id for metric in METRICS] + [metric.id for metric in TEAM_METRICS]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("metric", METRICS, ids=lambda metric: metric.id)
def test_every_metric_has_a_written_definition(metric: Metric) -> None:
    assert metric.definition.startswith(f"`{metric.id}`")


@pytest.mark.parametrize("metric", TEAM_METRICS, ids=lambda metric: metric.id)
def test_every_team_metric_has_a_written_definition(metric: TeamMetric) -> None:
    assert metric.definition.startswith(f"`{metric.id}`")


def test_compute_teams_gives_every_team_metric_to_both_teams() -> None:
    results = compute_teams(match_of(frames(row(player_idx=0), row(player_idx=1, team=1))))
    assert set(results) == {0, 1}
    for values in results.values():
        assert set(values) == {metric.id for metric in TEAM_METRICS}


def test_compute_gives_every_metric_to_every_player() -> None:
    results = compute(match_of(frames(row(player_idx=0), row(player_idx=1, team=1))))
    assert set(results) == {0, 1}
    for values in results.values():
        assert set(values) == {metric.id for metric in METRICS}


def test_a_roster_player_without_frames_still_gets_every_metric() -> None:
    match = match_of(frames(row(player_idx=0), row(player_idx=1, team=1)))
    only_one = match_of(
        frames(row(player_idx=0)),
        roster=match.events["roster"],
        pad_pickups=[pickup(0, "big", 0.0)],
    )
    results = compute(only_one)
    assert results[1]["boost.avg"] is None
    assert results[1]["boost.pads_big"] == 0.0


def test_a_match_loads_from_its_two_files(tmp_path: Path) -> None:
    import json

    match = match_of(frames(row()))
    match.frames.write_parquet(tmp_path / "frames.parquet")
    (tmp_path / "events.json").write_text(json.dumps(match.events), encoding="utf-8")
    loaded = load(tmp_path / "frames.parquet", tmp_path / "events.json")
    assert loaded.players == [0]
    assert loaded.frames.height == 1
