"""Loads `frames.parquet` and states the reference time every metric is measured on.

Frames are irregular (as few as 17 per second on recent replays, gaps of up to 430 ms), so a metric
never counts frames: it weighs each one by `dt_s`, the time since the previous kept frame.
"""

from collections.abc import Iterable
from pathlib import Path

import polars as pl

from ma_schemas import frames_problems
from rl_analysis.constants import BLUE_TEAM, LIVE_PHASES, MOTION_PHASES

_TYPES = {
    "UInt32": "uint32",
    "UInt8": "uint8",
    "Float32": "float32",
    "Boolean": "boolean",
}

type PerPlayer = dict[int, float | None]


class InvalidFramesError(ValueError):
    """The file does not have the columns of the schema. The message names columns, never values."""


def check(frames: pl.DataFrame) -> pl.DataFrame:
    columns = {name: _TYPES.get(str(kind), str(kind)) for name, kind in frames.schema.items()}
    found = frames_problems(columns)
    if found:
        raise InvalidFramesError("invalid frames.parquet: " + "; ".join(found[:10]))
    return frames


def read(path: Path) -> pl.DataFrame:
    return check(pl.read_parquet(path))


def _in_phases(phases: Iterable[int]) -> pl.Expr:
    return pl.col("phase").is_in([int(phase) for phase in phases])


def _counted() -> pl.Expr:
    """A car that is there and not demolished: a demolished car keeps a wrong position."""
    return pl.col("present") & ~pl.col("demolished")


def in_motion() -> pl.Expr:
    """Reference time of boost and movement: kickoff waiting and live play."""
    return _counted() & _in_phases(MOTION_PHASES)


def in_live_play() -> pl.Expr:
    """Reference time of positioning: live play only."""
    return _counted() & _in_phases(LIVE_PHASES)


def relative_y(column: str) -> pl.Expr:
    """`y` as seen by the player's team: positive towards the goal it attacks. Blue defends y < 0,
    so orange sees the field mirrored."""
    return pl.when(pl.col("team") == BLUE_TEAM).then(pl.col(column)).otherwise(-pl.col(column))


def players(frames: pl.DataFrame) -> list[int]:
    return sorted(int(index) for index in frames["player_idx"].unique().to_list())


def _per_player(frames: pl.DataFrame, numerator: pl.Expr, denominator: pl.Expr) -> PerPlayer:
    """Numerator over denominator for each player, None when there is no time to divide by."""
    sums = frames.group_by("player_idx").agg(
        numerator.sum().alias("numerator"), denominator.sum().alias("denominator")
    )
    found = {
        int(row["player_idx"]): (
            float(row["numerator"]) / float(row["denominator"]) if row["denominator"] > 0 else None
        )
        for row in sums.iter_rows(named=True)
    }
    return {player: found.get(player) for player in players(frames)}


def time_average(frames: pl.DataFrame, mask: pl.Expr, value: pl.Expr) -> PerPlayer:
    """The average of `value` over the time where `mask` holds. Frames where `value` is unknown are
    left out of both sides."""
    kept = mask & value.is_not_null()
    weight = pl.when(kept).then(pl.col("dt_s")).otherwise(0.0)
    return _per_player(frames, weight * value.fill_null(0.0), weight)


def time_share(
    frames: pl.DataFrame, mask: pl.Expr, condition: pl.Expr, *, known: pl.Expr | None = None
) -> PerPlayer:
    """The percentage of the time where `mask` holds that `condition` also holds. `known` leaves
    out frames where the condition cannot be judged, from both sides."""
    base = mask if known is None else mask & known
    weight = pl.when(base).then(pl.col("dt_s")).otherwise(0.0)
    hit = pl.when(base & condition.fill_null(value=False)).then(pl.col("dt_s")).otherwise(0.0)
    shares = _per_player(frames, hit, weight)
    return {player: None if share is None else 100.0 * share for player, share in shares.items()}
