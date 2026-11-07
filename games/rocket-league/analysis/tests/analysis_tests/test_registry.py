"""Every metric is defined and named once."""

import pytest

from rl_analysis.registry import METRICS, compute

from .synthetic import frames, row


def test_ids_are_unique() -> None:
    ids = [metric.id for metric in METRICS]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("metric", METRICS, ids=lambda metric: metric.id)
def test_every_metric_has_a_written_definition(metric: object) -> None:
    definition = metric.definition  # type: ignore[attr-defined]
    assert definition.startswith(f"`{metric.id}`")  # type: ignore[attr-defined]


def test_compute_gives_every_metric_to_every_player() -> None:
    results = compute(frames(row(player_idx=0), row(player_idx=1, team=1)))
    assert set(results) == {0, 1}
    for values in results.values():
        assert set(values) == {metric.id for metric in METRICS}
