"""Kickoffs (T13.1 and T13.2 of docs/PLAN-V2.md), read from the parser's `kickoffs` (DV7).

subtr-actor finds each kickoff, its type, its outcome and whether a goal followed. Who took it for
each team comes from the touches, as the plan defines it: the first of the team to touch the ball
once the countdown is over, within `thresholds.KICKOFF_TOUCH_MAX`. A team that does not touch the
ball by then had no taker. On the corpus, this taker is subtr-actor's own in 97 % of the cases, with
the same time to the ball.

The outcome is subtr-actor's (`kickoff.rs`): won by the team that sends the ball at least 256 uu
into the opponents' half 0.5 s after the first touch, neutral otherwise. A kickoff goal is one
scored within 12 s of it, by either team.

A match parsed before rl-parse 0.2.0, without kickoffs or touches, has none of these metrics.
"""

from bisect import bisect_left
from collections import Counter, defaultdict
from dataclasses import dataclass

import polars as pl

from ma_schemas.types import Kickoff as KickoffEvent
from rl_analysis.constants import Phase
from rl_analysis.frames import PerPlayer
from rl_analysis.match import Match
from rl_analysis.possession import TEAMS, PerTeam
from rl_analysis.thresholds import KICKOFF_TOUCH_MAX

# How far a goal of `events["goals"]` may sit from the kickoff's own goal time to be that goal.
_GOAL_MATCH_S = 1.0


@dataclass(frozen=True)
class Taker:
    player: int
    team: int
    time_to_ball_s: float


@dataclass(frozen=True)
class Kickoff:
    """`go_s`: the end of the countdown, when the cars may move."""

    go_s: float
    kind: str
    winner_team: int | None
    goal_team: int | None
    takers: tuple[Taker, ...]


def _timeline(match: Match) -> tuple[list[float], list[int]]:
    per_frame = match.frames.group_by("frame").agg(
        pl.col("time_s").first(), pl.col("phase").first()
    )
    ordered = per_frame.sort("time_s")
    return ordered["time_s"].to_list(), ordered["phase"].to_list()


def resolve(match: Match) -> list[Kickoff] | None:
    """The match's kickoffs with their takers, or None without detected kickoffs or touches."""
    events = match.events
    found, touches = events["kickoffs"], events["touches"]
    if found is None or touches is None:
        return None
    times, phases = _timeline(match)
    ordered = sorted(touches, key=lambda touch: touch["time_s"])
    touch_times = [touch["time_s"] for touch in ordered]
    resolved = []
    for kickoff in found:
        # The first frame of the kickoff where the cars may move.
        start = bisect_left(times, kickoff["start_time_s"])
        go_s = next(
            (
                times[row]
                for row in range(start, len(times))
                if times[row] <= kickoff["end_time_s"]
                and phases[row] in (Phase.KICKOFF_WAITING, Phase.ACTIVE)
            ),
            None,
        )
        if go_s is None:
            continue
        last = min(kickoff["end_time_s"], go_s + KICKOFF_TOUCH_MAX.value)
        takers: dict[int, Taker] = {}
        for index in range(bisect_left(touch_times, go_s), len(ordered)):
            touch = ordered[index]
            if touch["time_s"] > last:
                break
            if touch["team"] not in takers:
                takers[touch["team"]] = Taker(
                    touch["player_idx"], touch["team"], touch["time_s"] - go_s
                )
        resolved.append(
            Kickoff(
                go_s=go_s,
                kind=kickoff["kickoff_type"],
                winner_team=kickoff["winner_team"],
                goal_team=_goal_team(match, kickoff),
                takers=tuple(takers[team] for team in sorted(takers)),
            )
        )
    return resolved


def _goal_team(match: Match, kickoff: KickoffEvent) -> int | None:
    """The team that scored the kickoff's goal, found among the match's goals by its time."""
    if not kickoff["goal"] or kickoff["time_to_goal_s"] is None:
        return None
    since = kickoff["first_touch_time_s"] or kickoff["end_time_s"]
    at = since + kickoff["time_to_goal_s"]
    near = [goal for goal in match.events["goals"] if abs(goal["time_s"] - at) <= _GOAL_MATCH_S]
    return near[0]["team"] if near else None


def _per_player(match: Match) -> dict[int, list[tuple[Kickoff, Taker]]] | None:
    kickoffs = resolve(match)
    if kickoffs is None:
        return None
    taken: dict[int, list[tuple[Kickoff, Taker]]] = defaultdict(list)
    for kickoff in kickoffs:
        for taker in kickoff.takers:
            taken[taker.player].append((kickoff, taker))
    return taken


def taken(match: Match) -> PerPlayer:
    """`kick.taken`: kickoffs where the player is the first of their team to touch the ball, within
    6 s of the countdown's end. A count."""
    per_player = _per_player(match)
    if per_player is None:
        return dict.fromkeys(match.players)
    return {player: float(len(per_player.get(player, []))) for player in match.players}


def won_share(match: Match) -> PerPlayer:
    """`kick.won_pct`: share of the kickoffs the player took that their team won, the ball sent into
    the opponents' half 0.5 s after the first touch (subtr-actor's outcome); a neutral one is not
    won. In %; None when the player took none."""
    per_player = _per_player(match)
    if per_player is None:
        return dict.fromkeys(match.players)
    shares: PerPlayer = {}
    for player in match.players:
        mine = per_player.get(player, [])
        won = sum(kickoff.winner_team == taker.team for kickoff, taker in mine)
        shares[player] = 100.0 * won / len(mine) if mine else None
    return shares


def time_to_ball(match: Match) -> PerPlayer:
    """`kick.time_to_ball`: mean time from the countdown's end to the player's first touch, over the
    kickoffs they took. In seconds; None when they took none."""
    per_player = _per_player(match)
    if per_player is None:
        return dict.fromkeys(match.players)
    return {
        player: (
            sum(taker.time_to_ball_s for _, taker in per_player[player]) / len(per_player[player])
            if per_player.get(player)
            else None
        )
        for player in match.players
    }


def goals_conceded(match: Match) -> PerTeam:
    """`kick.goals_conceded`: goals the team conceded within 12 s of a kickoff (subtr-actor's
    kickoff goal). A count."""
    kickoffs = resolve(match)
    if kickoffs is None:
        return dict.fromkeys(TEAMS)
    scored = Counter(kickoff.goal_team for kickoff in kickoffs if kickoff.goal_team is not None)
    return {team: float(scored[1 - team]) for team in TEAMS}
