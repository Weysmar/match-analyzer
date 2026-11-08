"""Boost metrics. Reference time: kickoff waiting and live play, car there and not demolished. Boost
goes from 0 to 100; a frame with no boost value is left out."""

from collections import Counter

import polars as pl

from rl_analysis.constants import BOOST_FULL_MIN, BOOST_ZERO_MAX, MOTION_PHASES
from rl_analysis.frames import PerPlayer, in_motion, ratio, time_average, time_share
from rl_analysis.match import Match

_BOOST = pl.col("boost")
_KNOWN = _BOOST.is_not_null()


def average(match: Match) -> PerPlayer:
    """`boost.avg`: the player's boost, averaged over time. In %."""
    return time_average(match.frames, in_motion(), _BOOST)


def time_empty(match: Match) -> PerPlayer:
    """`boost.pct_zero`: share of the time with an empty tank, at most 1/255 of it. In %."""
    return time_share(match.frames, in_motion(), _BOOST <= BOOST_ZERO_MAX, known=_KNOWN)


def time_full(match: Match) -> PerPlayer:
    """`boost.pct_full`: share of the time with a full tank, at least 254/255 of it. In %."""
    return time_share(match.frames, in_motion(), _BOOST >= BOOST_FULL_MIN, known=_KNOWN)


def with_drops(frames: pl.DataFrame) -> pl.DataFrame:
    """Adds `drop`: how much boost the player lost since their previous known value, 0 when it
    rose. Frames go in order of time for each player."""
    previous = _BOOST.forward_fill().shift(1).over("player_idx")
    return frames.sort("player_idx", "frame").with_columns(
        (previous - _BOOST).clip(lower_bound=0.0).fill_null(0.0).alias("drop")
    )


def used_per_minute(match: Match) -> PerPlayer:
    """`boost.used_per_min`: boost consumed, per minute of reference time. In % per minute.

    Consumption is the sum of the falls of the boost from one frame to the next, as subtr-actor's
    `bpm()` counts boost picked up instead. A fall counts on a frame of reference time only: the
    reset to 33 % at a kickoff happens during the countdown, and does not count as boost used.
    Confirmed by `boost_active` times the rate of consumption, within 5 % (A5).
    """
    frames = with_drops(match.frames)
    kept = in_motion() & _KNOWN
    per_second = ratio(
        frames,
        pl.when(kept).then(pl.col("drop")).otherwise(0.0),
        pl.when(kept).then(pl.col("dt_s")).otherwise(0.0),
    )
    return {player: None if value is None else 60 * value for player, value in per_second.items()}


def _pickups(match: Match) -> list[tuple[int, str, float]]:
    """Pickups on reference time, already deduplicated by `rl-parse` (A18): player, size, and the
    pad's y relative to the player's team."""
    # A player who switches teams in a private match attacks the other half afterwards (A52).
    team_at = {
        (player, frame): team
        for player, frame, team in match.frames.select("player_idx", "frame", "team").iter_rows()
    }
    found: list[tuple[int, str, float]] = []
    for pickup in match.events["pad_pickups"]:
        if pickup["phase"] not in MOTION_PHASES:
            continue
        player = pickup["player_idx"]
        team = team_at.get((player, pickup["frame"]), match.team_of(player))
        sign = 1.0 if team == 0 else -1.0
        found.append((player, pickup["size"], sign * pickup["y"]))
    return found


def _count(match: Match, counted: Counter[int]) -> PerPlayer:
    """A count per player, or None for all when the replay holds no pickup at all. No real match
    goes without one, if only at a kickoff: an old replay of the corpus, 12 minutes long, simply
    does not replicate them (A51). Saying 0 there would be saying something false."""
    if not match.events["pad_pickups"]:
        return dict.fromkeys(match.players)
    return {player: float(counted[player]) for player in match.players}


def pads_big(match: Match) -> PerPlayer:
    """`boost.pads_big`: big pads picked up during kickoff waiting and live play. A count."""
    return _count(match, Counter(p for p, size, _ in _pickups(match) if size == "big"))


def pads_small(match: Match) -> PerPlayer:
    """`boost.pads_small`: small pads picked up during kickoff waiting and live play. A count."""
    return _count(match, Counter(p for p, size, _ in _pickups(match) if size == "small"))


def pads_enemy_half(match: Match) -> PerPlayer:
    """`boost.pads_enemy_half`: pads of either size picked up in the opponents' half, where y
    relative to the team is above 0. A count."""
    return _count(match, Counter(p for p, _, y in _pickups(match) if y > 0))
