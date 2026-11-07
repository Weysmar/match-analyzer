"""The V1 metrics (section 8.2 of CLAUDE.md, step 7 of docs/PLAN.md), each with its id and unit.
Adding one needs no migration: `player_match_metrics` holds a row per player and metric."""

from collections.abc import Callable
from dataclasses import dataclass

import polars as pl

from rl_analysis import boost
from rl_analysis.frames import PerPlayer


@dataclass(frozen=True)
class Metric:
    id: str
    unit: str
    compute: Callable[[pl.DataFrame], PerPlayer]

    @property
    def definition(self) -> str:
        """The written definition, which lives in the computing function's docstring."""
        return (self.compute.__doc__ or "").strip()


METRICS: tuple[Metric, ...] = (
    Metric("boost.avg", "%", boost.average),
    Metric("boost.pct_zero", "%", boost.time_empty),
    Metric("boost.pct_full", "%", boost.time_full),
)


def compute(frames: pl.DataFrame) -> dict[int, dict[str, float | None]]:
    """Every metric for every player of the match, by `player_idx`."""
    results: dict[int, dict[str, float | None]] = {}
    for metric in METRICS:
        for player, value in metric.compute(frames).items():
            results.setdefault(player, {})[metric.id] = value
    return results
