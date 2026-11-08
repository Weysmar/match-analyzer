"""Movement metrics. Reference time: kickoff waiting and live play, car there and not demolished."""

import polars as pl

from rl_analysis.constants import GROUND_MAX_Z, HIGH_AIR_MIN_Z, SUPERSONIC_SPEED
from rl_analysis.frames import PerPlayer, in_motion, time_average, time_share
from rl_analysis.match import Match

_SPEED = (pl.col("vx") ** 2 + pl.col("vy") ** 2 + pl.col("vz") ** 2).sqrt()
_Z = pl.col("z")


def speed_average(match: Match) -> PerPlayer:
    """`move.speed_avg`: the car's speed, averaged over time. In uu/s. A frame with no velocity
    (0.6 % of them) is left out."""
    return time_average(match.frames, in_motion(), _SPEED)


def time_supersonic(match: Match) -> PerPlayer:
    """`move.pct_supersonic`: share of the time at 2200 uu/s or more, a convention (A11). In %."""
    return time_share(
        match.frames, in_motion(), _SPEED >= SUPERSONIC_SPEED, known=_SPEED.is_not_null()
    )


def time_on_ground(match: Match) -> PerPlayer:
    """`move.pct_ground`: share of the time with the car at 20 uu or lower (D7). In %. Driving on
    a wall counts as air: the data says nothing of the ground."""
    return time_share(match.frames, in_motion(), _Z <= GROUND_MAX_Z, known=_Z.is_not_null())


def time_in_low_air(match: Match) -> PerPlayer:
    """`move.pct_low_air`: share of the time between the ground and high air (D7). In %."""
    low = (_Z > GROUND_MAX_Z) & (_Z < HIGH_AIR_MIN_Z)
    return time_share(match.frames, in_motion(), low, known=_Z.is_not_null())


def time_in_high_air(match: Match) -> PerPlayer:
    """`move.pct_high_air`: share of the time high enough to clear a ball resting on the ground,
    from 735.5 uu (D7). In %."""
    return time_share(match.frames, in_motion(), _Z >= HIGH_AIR_MIN_Z, known=_Z.is_not_null())
