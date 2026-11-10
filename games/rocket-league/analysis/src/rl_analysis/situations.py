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

Players are `player_idx` here; the callers turn them into `match_player_id`. No name ever.
"""

from bisect import bisect_right
from dataclasses import dataclass, field

import polars as pl

from rl_analysis import clock, commits, kickoffs, possession
from rl_analysis.match import Match

KINDS = ("turnover", "kickoff", "fifty_fifty", "double_commit")


@dataclass(frozen=True)
class Situation:
    kind: str
    time_s: float
    # Seconds of play then, on the game clock; None before any frame.
    clock_s: float | None
    team: int | None
    players: tuple[int, ...]
    # Facts of the kind, never an id: shown, not judged.
    details: dict[str, object] = field(default_factory=dict)


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
    return sorted(found, key=lambda situation: (situation.time_s, KINDS.index(situation.kind)))
