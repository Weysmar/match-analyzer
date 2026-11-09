"""The 2D view's document, `match2d` (T12.1 and section 5.6 of docs/PLAN-V2.md).

The analysis samples the frames on a regular grid of `RATE_HZ` (DV2), from the first frame to the
last, and the browser draws the match from it. Frames are irregular: each sample is interpolated
linearly between the frames around it, positions as whole uu. The spike measured 16 uu of error at
the 95th percentile at 15 Hz, a seventh of a car's length.

The document follows `packages/schemas/match2d.schema.json`. Positions and the clock are written as
differences from one sample to the next (`DELTA_FIELDS`), small numbers that gzip packs well: the
first value is absolute, then each one adds to the previous.

No name and no platform id: players are named by `match_player_id`, which the caller maps from
`player_idx`. The site takes names from the match sheet, with the same privacy rules.

`situations` lists what the detections found, for the view and its labeling mode (T12.7): the
turnovers of `possession` for now, then kickoffs, duels, double commits and overcommits
(steps 13 and 14 of docs/PLAN-V2.md). Null without detected touches.
"""

from collections.abc import Mapping
from itertools import pairwise
from typing import Any

import polars as pl

from rl_analysis import clock, possession
from rl_analysis.match import Match

VERSION = 1
RATE_HZ = 15
# Bits of a player's `flags`.
PRESENT = 1
DEMOLISHED = 2
BOOSTING = 4
DELTA_FIELDS = ("clock_ds", "ball.x", "ball.y", "ball.z", "players.x", "players.y", "players.z")


def _grid(match: Match) -> pl.DataFrame:
    """The sample times, from the first frame to the last."""
    start = float(match.frames["time_s"].min())  # type: ignore[arg-type]
    end = float(match.frames["time_s"].max())  # type: ignore[arg-type]
    count = int((end - start) * RATE_HZ) + 1
    return pl.DataFrame(
        {"time_s": [start + index / RATE_HZ for index in range(count)]},
        schema={"time_s": pl.Float64},
    )


def _interpolated(points: pl.DataFrame, grid: pl.DataFrame, columns: list[str]) -> pl.DataFrame:
    """Each column at each grid time, linear between the points around it; before the first point
    or after the last, the nearest one. `points` has `time_s` and the columns, no null."""
    points = points.with_columns(pl.col("time_s").cast(pl.Float64)).sort("time_s")
    before = points.select(
        "time_s", pl.col("time_s").alias("t0"), *[pl.col(c).alias(f"{c}_0") for c in columns]
    )
    after = points.select(
        "time_s", pl.col("time_s").alias("t1"), *[pl.col(c).alias(f"{c}_1") for c in columns]
    )
    joined = grid.join_asof(before, on="time_s", strategy="backward").join_asof(
        after, on="time_s", strategy="forward"
    )
    span = pl.col("t1") - pl.col("t0")
    weight = pl.when(span > 0).then((pl.col("time_s") - pl.col("t0")) / span).otherwise(0.0)
    return joined.select(
        [
            pl.when(pl.col(f"{c}_0").is_null())
            .then(pl.col(f"{c}_1"))
            .when(pl.col(f"{c}_1").is_null())
            .then(pl.col(f"{c}_0"))
            .otherwise(pl.col(f"{c}_0") + (pl.col(f"{c}_1") - pl.col(f"{c}_0")) * weight)
            .alias(c)
            for c in columns
        ]
    )


def _latest(points: pl.DataFrame, grid: pl.DataFrame, columns: list[str]) -> pl.DataFrame:
    """Each column at each grid time as the last point at or before it said, or the first point
    before any: for states and angles, which do not interpolate."""
    points = points.with_columns(pl.col("time_s").cast(pl.Float64)).sort("time_s")
    joined = grid.join_asof(points, on="time_s", strategy="backward")
    first = points.head(1)
    return joined.select(
        [pl.col(c).fill_null(first[c][0] if first.height else None) for c in columns]
    )


def _whole(series: pl.Series) -> list[int]:
    return [round(value) for value in series.fill_null(0).to_list()]


def delta(values: list[int]) -> list[int]:
    """The first value, then each one minus the previous."""
    return values[:1] + [b - a for a, b in pairwise(values)]


def undelta(values: list[int]) -> list[int]:
    """The other way round, as the browser decodes it."""
    total, decoded = 0, []
    for value in values:
        total += value
        decoded.append(total)
    return decoded


def _heading() -> pl.Expr:
    """The car's yaw in whole degrees, from its quaternion: 0 points to +x, 90 to +y."""
    qx, qy, qz, qw = (pl.col(name) for name in ("qx", "qy", "qz", "qw"))
    return pl.arctan2(2 * (qw * qz + qx * qy), 1 - 2 * (qy * qy + qz * qz)).degrees()


def _player(frames: pl.DataFrame, grid: pl.DataFrame) -> dict[str, list[int]]:
    """One player's columns. A car away or demolished keeps its last position, flagged so: the
    view hides it rather than drawing it at a wrong place."""
    flags = frames.select(
        "time_s",
        (
            (pl.col("present") & ~pl.col("demolished")).cast(pl.Int64) * PRESENT
            + pl.col("demolished").cast(pl.Int64) * DEMOLISHED
            + pl.col("boost_active").cast(pl.Int64) * BOOSTING
        ).alias("flags"),
        pl.col("boost").fill_null(strategy="forward").fill_null(0.0).alias("boost"),
    )
    shown = frames.filter(pl.col("present") & ~pl.col("demolished") & pl.col("x").is_not_null())
    if shown.height == 0:
        positions = pl.DataFrame({c: [0.0] * grid.height for c in ("x", "y", "z", "yaw")})
    else:
        moved = _interpolated(shown.select("time_s", "x", "y", "z"), grid, ["x", "y", "z"])
        turned = _latest(
            shown.filter(pl.col("qw").is_not_null()).select("time_s", _heading().alias("yaw")),
            grid,
            ["yaw"],
        )
        positions = pl.concat([moved, turned], how="horizontal")
    states = _latest(flags, grid, ["flags", "boost"])
    return {
        "x": delta(_whole(positions["x"])),
        "y": delta(_whole(positions["y"])),
        "z": delta(_whole(positions["z"])),
        "yaw": _whole(positions["yaw"]),
        "boost": _whole(states["boost"]),
        "flags": _whole(states["flags"]),
    }


def build(match: Match, ids: Mapping[int, int]) -> dict[str, Any]:
    """The document of a match whose players `ids` maps from `player_idx` to `match_player_id`.
    A player missing from `ids` is left out, and so are their events."""
    grid = _grid(match)
    start_s = float(grid["time_s"][0])
    frames = match.frames.sort("time_s")
    per_frame = frames.group_by("frame").agg(
        pl.col("time_s").first(),
        pl.col("phase").first(),
        pl.col("ball_x").first(),
        pl.col("ball_y").first(),
        pl.col("ball_z").first(),
    )
    with_ball = per_frame.drop_nulls(["ball_x", "ball_y", "ball_z"])
    ball = _interpolated(
        with_ball.select("time_s", "ball_x", "ball_y", "ball_z"),
        grid,
        ["ball_x", "ball_y", "ball_z"],
    )
    phases = _latest(per_frame.select("time_s", "phase"), grid, ["phase"])
    game_clock = clock.per_frame(frames).join(per_frame.select("frame", "time_s"), on="frame")
    clock_s = _interpolated(game_clock.select("time_s", "clock"), grid, ["clock"])["clock"] * 10

    def known(player: int | None) -> int | None:
        return None if player is None else ids.get(player)

    players = []
    for player in sorted(ids):
        rows = frames.filter(pl.col("player_idx") == player)
        if rows.height == 0:
            continue
        team = int(rows["team"].mode().sort()[0])
        players.append({"id": ids[player], "team": team} | _player(rows, grid))

    goals_clock = clock.compute(match).goals_s
    touches = match.events["touches"]
    resolved = possession.resolve(match)
    return {
        "version": VERSION,
        "rate_hz": RATE_HZ,
        "start_s": round(start_s, 3),
        "samples": grid.height,
        "delta": list(DELTA_FIELDS),
        "clock_ds": delta(_whole(clock_s)),
        "phase": _whole(phases["phase"]),
        "ball": {
            "x": delta(_whole(ball["ball_x"])),
            "y": delta(_whole(ball["ball_y"])),
            "z": delta(_whole(ball["ball_z"])),
        },
        "players": players,
        "goals": [
            {
                "time_s": round(goal["time_s"], 3),
                "clock_s": None if at is None else round(at, 1),
                "team": goal["team"],
                "player": known(goal["player_idx"]),
            }
            for goal, at in zip(match.events["goals"], goals_clock, strict=True)
        ],
        "demolitions": [
            {
                "time_s": round(demo["time_s"], 3),
                "attacker": known(demo["attacker_idx"]),
                "victim": known(demo["victim_idx"]),
            }
            for demo in match.events["demolitions"]
        ],
        # Null when the parser did not detect them, as for the metrics.
        "touches": None
        if touches is None
        else [
            {"time_s": round(touch["time_s"], 3), "player": ids[touch["player_idx"]]}
            for touch in touches
            if touch["player_idx"] in ids
        ],
        "situations": None if resolved is None else _situations(resolved, ids),
    }


def _situations(resolved: possession.Possession, ids: Mapping[int, int]) -> list[dict[str, Any]]:
    """The detected situations, in time order. A turnover is at the winner's first touch; its
    players are the one who took the ball, then the one who lost it, those known."""
    found = [
        {
            "kind": "turnover",
            "time_s": round(turnover.time_s, 3),
            "team": turnover.team,
            "players": [
                ids[player]
                for player in (turnover.won_by, turnover.lost_by)
                if player is not None and player in ids
            ],
        }
        for turnover in resolved.turnovers
    ]
    return sorted(found, key=lambda situation: situation["time_s"])
