"""The situations a match is made of (T13.4 of docs/PLAN-V2.md): what the detections found, each at
a moment, about a team and some players. The 2D view marks them on its cursor and its labeling mode
asks about them; the worker stores them in `match_situations` for the match sheet (step 16).

- `turnover`: a possession lost on an opponent's touch (`possession`), at the winner's first touch;
  its team won the ball; its players took it, then lost it.
- `kickoff`: at the end of the countdown (`kickoffs`); its team won it, if anyone did; its players
  are the takers, blue's first.
- `fifty_fifty`: a duel (subtr-actor's 50/50, read from the parser), at its first touch; its team
  has the ball afterwards, if any; its players are blue's, then orange's.
- `double_commit`: two teammates engaged on the ball together (`commits`), when they first were;
  its team is theirs; its players are them.
- `overcommit`: the whole team ahead of the ball while the opponents hold it (`overcommits`), when
  it got there; its team is the one caught; its players are all of it.
- `goal_context`: a goal conceded (`conceded`), at the goal; its team is the one that conceded it;
  its players are that team's, as they stood at the shot; its tags say which usual causes were
  there, its details hold the facts.

Players are `player_idx` here, in `players` and in `details`, where a player is always the value of
a `player` key; the callers turn both into `match_player_id` (`with_ids`). No name ever.
"""

from bisect import bisect_right
from collections.abc import Callable
from dataclasses import dataclass, field

import polars as pl

from rl_analysis import clock, commits, conceded, kickoffs, overcommits, possession
from rl_analysis.match import Match

KINDS = ("turnover", "kickoff", "fifty_fifty", "double_commit", "overcommit", "goal_context")


@dataclass(frozen=True)
class Situation:
    kind: str
    time_s: float
    # Seconds of play then, on the game clock; None before any frame.
    clock_s: float | None
    team: int | None
    players: tuple[int, ...]
    # Facts of the kind, never a platform id: shown, not judged.
    details: dict[str, object] = field(default_factory=dict)
    # What the situation is said to be: the tags of a goal context.
    tags: tuple[str, ...] = ()


def with_ids(value: object, ids: dict[int, int]) -> object:
    """`details` with each `player` turned from `player_idx` into `match_player_id`, None when the
    player has none."""
    if isinstance(value, dict):
        return {
            key: (
                ids.get(item) if key == "player" and isinstance(item, int) else with_ids(item, ids)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [with_ids(item, ids) for item in value]
    return value


def _clock(match: Match) -> tuple[list[float], list[float]]:
    """Each frame's time and the game clock at its end."""
    per_frame = clock.per_frame(match.frames).join(
        match.frames.group_by("frame").agg(pl.col("time_s").first()), on="frame"
    )
    ordered = per_frame.sort("time_s")
    return ordered["time_s"].to_list(), ordered["clock"].to_list()


def detect(match: Match) -> list[Situation] | None:
    """Every situation of the match, in time order; None without detected touches, which every
    detection here relies on. A detection the parser did not run is left out."""
    resolved = possession.resolve(match)
    if resolved is None:
        return None
    times, clocks = _clock(match)

    def clock_at(time_s: float) -> float | None:
        row = bisect_right(times, time_s) - 1
        return None if row < 0 else round(float(clocks[row]), 1)

    found = [
        Situation(
            "turnover",
            turnover.time_s,
            clock_at(turnover.time_s),
            turnover.team,
            tuple(p for p in (turnover.won_by, turnover.lost_by) if p is not None),
        )
        for turnover in resolved.turnovers
    ]
    for kickoff in kickoffs.resolve(match) or []:
        found.append(
            Situation(
                "kickoff",
                kickoff.go_s,
                clock_at(kickoff.go_s),
                kickoff.winner_team,
                tuple(taker.player for taker in kickoff.takers),
                {"kickoff_type": kickoff.kind, "goal": kickoff.goal_team is not None},
            )
        )
    for duel in match.events["fifty_fifties"] or []:
        found.append(
            Situation(
                "fifty_fifty",
                duel["start_time_s"],
                clock_at(duel["start_time_s"]),
                duel["possession_team"],
                tuple(
                    p for p in (duel["blue_player_idx"], duel["orange_player_idx"]) if p is not None
                ),
                {"is_kickoff": duel["is_kickoff"], "contact_winner": duel["winner_team"]},
            )
        )
    for commit in commits.resolve(match) or []:
        found.append(
            Situation(
                "double_commit",
                commit.time_s,
                clock_at(commit.time_s),
                commit.team,
                commit.players,
                {"punished": commit.punished},
            )
        )
    for overcommit in overcommits.resolve(match) or []:
        found.append(
            Situation(
                "overcommit",
                overcommit.time_s,
                clock_at(overcommit.time_s),
                overcommit.team,
                overcommit.players,
                {"duration_s": round(overcommit.duration_s, 2)},
            )
        )
    for context in conceded.resolve(match) or []:
        found.append(
            Situation(
                "goal_context",
                context.time_s,
                clock_at(context.time_s),
                context.team,
                tuple(defender.player for defender in context.defenders),
                _goal_details(context, clock_at),
                context.tags,
            )
        )
    return sorted(found, key=lambda situation: (situation.time_s, KINDS.index(situation.kind)))


def _rounded(value: float | None, digits: int = 0) -> float | None:
    return None if value is None else round(value, digits)


def _goal_details(
    context: conceded.GoalContext, clock_at: Callable[[float], float | None]
) -> dict[str, object]:
    """The facts of a goal conceded: seconds of play, distances in uu, boost from 0 to 100, the
    ball's `y` as the conceding team sees it (negative in its own half)."""
    lost = context.lost_ball
    return {
        "window_s": round(context.window_s, 1),
        "shot_clock_s": clock_at(context.shot_s),
        "last_touch": None
        if context.last_touch is None
        else {"player": context.last_touch, "team": context.last_touch_team},
        "lost_ball": None
        if lost is None
        else {
            "player": lost.lost_by,
            "clock_s": clock_at(lost.time_s),
            "before_goal_s": _rounded(lost.before_goal_s, 1),
            "ball_y": _rounded(lost.ball_y),
            "roles": [{"player": player, "role": role} for player, role in lost.roles.items()],
        },
        "defenders": [
            {
                "player": defender.player,
                "goal_distance": _rounded(defender.goal_distance),
                "boost": _rounded(defender.boost),
                "demolished": defender.demolished,
                "last_back": defender.player == context.last_back,
            }
            for defender in context.defenders
        ],
    }
