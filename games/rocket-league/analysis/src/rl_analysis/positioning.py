"""Positioning metrics. Reference time: live play only, car there and not demolished. Every `y` is
relative to the player's team: positive towards the goal it attacks."""

from collections import Counter

import polars as pl

from rl_analysis.constants import THIRD_Y
from rl_analysis.frames import PerPlayer, in_live_play, relative_y, time_average, time_share
from rl_analysis.match import Match

_Y = relative_y("y")
_BALL_Y = relative_y("ball_y")
_BALL_KNOWN = pl.col("ball_y").is_not_null()


def thirds(match: Match, cut: float = THIRD_Y) -> tuple[PerPlayer, PerPlayer, PerPlayer]:
    """Shares of live play in the defensive, middle and attacking thirds, cut at ±`cut`. The plan
    cuts at true thirds (D4); subtr-actor at ±2300, which the tests use to check the computation."""
    frames = match.frames
    known = _Y.is_not_null()
    return (
        time_share(frames, in_live_play(), -cut > _Y, known=known),
        time_share(frames, in_live_play(), (-cut <= _Y) & (cut >= _Y), known=known),
        time_share(frames, in_live_play(), cut < _Y, known=known),
    )


def defensive_third(match: Match) -> PerPlayer:
    """`pos.pct_def_third`: share of live play in the third the team defends, y relative to the team
    below -5120/3 (D4). In %."""
    return thirds(match)[0]


def middle_third(match: Match) -> PerPlayer:
    """`pos.pct_mid_third`: share of live play in the middle third, between ±5120/3 (D4). In %."""
    return thirds(match)[1]


def attacking_third(match: Match) -> PerPlayer:
    """`pos.pct_att_third`: share of live play in the third the team attacks, y relative to the
    team above 5120/3 (D4). In %."""
    return thirds(match)[2]


def ahead_and_behind(match: Match, margin: float = 0.0) -> tuple[PerPlayer, PerPlayer]:
    """Shares of live play ahead of the ball and behind it, along y relative to the team. The plan
    uses no margin; subtr-actor counts 150 uu around the ball as neither, which the tests use."""
    frames = match.frames
    known = _Y.is_not_null() & _BALL_KNOWN
    return (
        time_share(frames, in_live_play(), _BALL_Y + margin < _Y, known=known),
        time_share(frames, in_live_play(), _BALL_Y - margin > _Y, known=known),
    )


def ahead_of_ball(match: Match) -> PerPlayer:
    """`pos.pct_ahead_ball`: share of live play with the car nearer the goal it attacks than the
    ball is, along y relative to the team, with no margin. In %."""
    return ahead_and_behind(match)[0]


def behind_ball(match: Match) -> PerPlayer:
    """`pos.pct_behind_ball`: share of live play with the car nearer the goal it defends than the
    ball is, along y relative to the team, with no margin. In %."""
    return ahead_and_behind(match)[1]


def distance_to_ball(match: Match) -> PerPlayer:
    """`pos.dist_ball_avg`: the distance from the car to the ball in 3D, averaged over live play.
    In uu. A frame with no ball is left out."""
    distance = (
        (pl.col("x") - pl.col("ball_x")) ** 2
        + (pl.col("y") - pl.col("ball_y")) ** 2
        + (pl.col("z") - pl.col("ball_z")) ** 2
    ).sqrt()
    return time_average(match.frames, in_live_play(), distance)


def last_back(match: Match) -> PerPlayer:
    """`pos.pct_last_back`: share of live play as the player of the team nearest its own goal, along
    y relative to the team, among teammates there and not demolished on that frame. In %. No role
    logic, unlike subtr-actor (about 4 points apart). None for a player alone in their team, as in
    1v1, where the answer is always yes."""
    counted = in_live_play() & _Y.is_not_null()
    deepest = pl.when(counted).then(_Y).otherwise(None).min().over("frame", "team")
    frames = match.frames.with_columns((counted & (deepest == _Y)).alias("last_back"))
    shares = time_share(frames, in_live_play(), pl.col("last_back"))
    team_sizes = Counter(match.team_of(player) for player in match.players)
    return {
        player: None if team_sizes[match.team_of(player)] < 2 else shares.get(player)
        for player in match.players
    }


def _demolitions(match: Match, side: str) -> PerPlayer:
    counted = Counter(
        demolition[side]  # type: ignore[literal-required]
        for demolition in match.events["demolitions"]
        if demolition[side] is not None  # type: ignore[literal-required]
    )
    return {player: float(counted[player]) for player in match.players}


def demolitions_inflicted(match: Match) -> PerPlayer:
    """`event.demos_inflicted`: other cars the player demolished, over the whole match. A count."""
    return _demolitions(match, "attacker_idx")


def demolitions_taken(match: Match) -> PerPlayer:
    """`event.demos_taken`: times the player's car was demolished, over the whole match. A count."""
    return _demolitions(match, "victim_idx")
