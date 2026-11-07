"""Boost metrics. Reference time: kickoff waiting and live play, car there and not demolished. Boost
goes from 0 to 100; a frame with no boost value is left out."""

import polars as pl

from rl_analysis.constants import BOOST_FULL_MIN, BOOST_ZERO_MAX
from rl_analysis.frames import PerPlayer, in_motion, time_average, time_share

_BOOST = pl.col("boost")


def average(frames: pl.DataFrame) -> PerPlayer:
    """`boost.avg`: the player's boost, averaged over time. In %."""
    return time_average(frames, in_motion(), _BOOST)


def time_empty(frames: pl.DataFrame) -> PerPlayer:
    """`boost.pct_zero`: share of the time with an empty tank, at most 1/255 of it. In %."""
    return time_share(frames, in_motion(), _BOOST <= BOOST_ZERO_MAX, known=_BOOST.is_not_null())


def time_full(frames: pl.DataFrame) -> PerPlayer:
    """`boost.pct_full`: share of the time with a full tank, at least 254/255 of it. In %."""
    return time_share(frames, in_motion(), _BOOST >= BOOST_FULL_MIN, known=_BOOST.is_not_null())
