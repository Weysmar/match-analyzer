"""Touch metrics (T11.4 of docs/PLAN-V2.md), from the touches subtr-actor's detector finds in the
replay (DV1). A match parsed before rl-parse 0.2.0, or whose detection failed, has none: every
touch metric is then None, never 0.

Reference time of the rate: live play, car there and not demolished, like positioning.
"""

from collections import Counter

import polars as pl

from ma_schemas.types import Touch
from rl_analysis.constants import HIGH_AIR_MIN_Z
from rl_analysis.frames import PerPlayer, in_live_play
from rl_analysis.match import Match
from rl_analysis.thresholds import HARD_TOUCH_SPEED_CHANGE


def _touches(match: Match) -> list[Touch] | None:
    return match.events["touches"]


def _nothing(match: Match) -> PerPlayer:
    return dict.fromkeys(match.players)


def _share(match: Match, hit: Counter[int], known: Counter[int]) -> PerPlayer:
    return {
        player: 100.0 * hit[player] / known[player] if known[player] else None
        for player in match.players
    }


def count(match: Match) -> PerPlayer:
    """`touch.count`: the player's touches of the ball in live play. A count. subtr-actor only finds
    touches while the ball is live: all 21260 of the corpus fall in the active phase."""
    touches = _touches(match)
    if touches is None:
        return _nothing(match)
    counted = Counter(touch["player_idx"] for touch in touches)
    return {player: float(counted[player]) for player in match.players}


def per_minute(match: Match) -> PerPlayer:
    """`touch.per_min`: touches per minute of live play with the car there and not demolished. In
    touches per minute; None without such time."""
    touches = _touches(match)
    if touches is None:
        return _nothing(match)
    counted = Counter(touch["player_idx"] for touch in touches)
    minutes = (
        match.frames.filter(in_live_play())
        .group_by("player_idx")
        .agg((pl.col("dt_s").sum() / 60.0).alias("minutes"))
    )
    by_player = {int(row[0]): float(row[1]) for row in minutes.iter_rows()}
    return {
        player: counted[player] / by_player[player] if by_player.get(player) else None
        for player in match.players
    }


def share_aerial(match: Match) -> PerPlayer:
    """`touch.pct_aerial`: share of the player's touches made with the car in high air, from
    735.5 uu (D7, as `move.pct_high_air`). In %. The car's height is read in the frames at the
    touch, or just before; a touch whose height is unknown is left out of both sides."""
    touches = _touches(match)
    if not touches:
        # None: not detected. Empty: no touch, so no share either.
        return _nothing(match)
    at = pl.DataFrame(
        {
            "frame": [touch["frame"] for touch in touches],
            "player_idx": [touch["player_idx"] for touch in touches],
        },
        schema={"frame": pl.UInt32, "player_idx": pl.UInt8},
    ).sort("frame")
    cars = (
        match.frames.filter(pl.col("present") & pl.col("z").is_not_null())
        .select("frame", "player_idx", "z")
        .sort("frame")
    )
    # Both sides are sorted by frame above, so within each player too.
    heights = at.join_asof(
        cars, on="frame", by="player_idx", strategy="backward", check_sortedness=False
    )
    known: Counter[int] = Counter()
    hit: Counter[int] = Counter()
    for player, z in heights.select("player_idx", "z").iter_rows():
        if z is None:
            continue
        known[int(player)] += 1
        hit[int(player)] += z >= HIGH_AIR_MIN_Z
    return _share(match, hit, known)


def share_hard(match: Match) -> PerPlayer:
    """`touch.pct_hard`: share of the player's touches that change the ball's speed by 900 uu/s or
    more (`thresholds.HARD_TOUCH_SPEED_CHANGE`), a carry or a dribble aside. In %.

    subtr-actor's hard hit, rebuilt from its parts so the threshold stays ours (section 4 of
    docs/PLAN-V2.md): a touch it tags `control` above its soft threshold is a controlled one, the
    ball riding the car, and never a hit whatever the speed change. On the corpus, 2079 of 21260
    touches; with them left out, the count equals its `hard_hit` exactly."""
    touches = _touches(match)
    if touches is None:
        return _nothing(match)
    known = Counter(touch["player_idx"] for touch in touches)
    hit = Counter(
        touch["player_idx"]
        for touch in touches
        if touch["ball_speed_change"] >= HARD_TOUCH_SPEED_CHANGE.value
        and touch["kind"] != "control"
    )
    return _share(match, hit, known)
