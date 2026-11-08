"""The game clock, which the replay does not record: `time_s` counts the replay's own time,
countdowns, kickoff waits and goal celebrations included. The clock runs while the ball is in play,
so it is the sum of `dt_s` over active frames.

Measured on the corpus (A63): a five-minute match adds up to 302 to 311 s of active play, the clock
stopping a little later than the game's own (the ball must touch the ground after 0:00). Times given
from this clock are within a few seconds.
"""

from dataclasses import dataclass

import polars as pl

from rl_analysis.constants import Phase
from rl_analysis.match import Match

REGULATION_S = 300.0
# Overtime starts with a kickoff countdown straight after active play, which only the end of the
# regulation time causes; after a goal, the celebration comes first. Measured on the corpus: from
# 303 to 311 s of active play. The window leaves out a kickoff reset early in a private match, and
# matches of another length.
OVERTIME_EARLIEST_S = REGULATION_S - 5.0
OVERTIME_LATEST_S = REGULATION_S + 30.0
# A replay may open on a sliver of "active" frames before the first countdown.
MIN_ACTIVE_RUN_S = 1.0


@dataclass(frozen=True)
class Clock:
    """Seconds of play: the whole match, the start of overtime if there was one, and each goal in
    the order of `events["goals"]`."""

    length_s: float | None
    overtime_from_s: float | None
    goals_s: list[float | None]


def per_frame(frames: pl.DataFrame) -> pl.DataFrame:
    """One row per frame: its phase and the clock at its end."""
    return (
        frames.group_by("frame")
        .agg(pl.col("phase").first(), pl.col("dt_s").first())
        .sort("frame")
        .with_columns(
            pl.when(pl.col("phase") == int(Phase.ACTIVE))
            .then(pl.col("dt_s"))
            .otherwise(0.0)
            .cum_sum()
            .alias("clock")
        )
    )


def overtime_from(clock: pl.DataFrame) -> float | None:
    """The clock when overtime began, or None when the match ended in regulation time."""
    previous: int | None = None
    run_start = 0.0
    for phase, at in clock.select("phase", "clock").iter_rows():
        if phase == Phase.UNKNOWN or phase == previous:
            continue
        if phase == Phase.ACTIVE:
            run_start = at
        elif (
            previous == Phase.ACTIVE
            and phase == Phase.COUNTDOWN
            and at - run_start >= MIN_ACTIVE_RUN_S
            and OVERTIME_EARLIEST_S <= at <= OVERTIME_LATEST_S
        ):
            return float(at)
        previous = phase
    return None


def clock_at(clock: pl.DataFrame, frame: int) -> float | None:
    """The clock at the end of a frame, or None before the first one."""
    found = clock.filter(pl.col("frame") <= frame).tail(1)
    return None if found.height == 0 else float(found["clock"][0])


def compute(match: Match) -> Clock:
    clock = per_frame(match.frames)
    if clock.height == 0:
        return Clock(None, None, [None for _ in match.events["goals"]])
    return Clock(
        length_s=float(clock["clock"].max()),  # type: ignore[arg-type]
        overtime_from_s=overtime_from(clock),
        goals_s=[clock_at(clock, goal["frame"]) for goal in match.events["goals"]],
    )
