"""Double commits (T14.3 of docs/PLAN-V2.md, section 5.4).

Two teammates engaged on the ball at once (`engagement`), for at least `DOUBLE_COMMIT_MIN_OVERLAP`
(0.25 s), in a sequence a touch ends, by one of them or an opponent, within `DOUBLE_COMMIT_RESOLVE`
(1.5 s) of its start. It is punished when the opponents shoot or score within `DOUBLE_COMMIT_PUNISH`
(5 s) of that touch. Going in two is a choice at a kickoff: a sequence that starts between the end
of the countdown and `KICKOFF_SCRAMBLE` (2 s) after the kickoff's first touch does not count.

The three durations are conventions of the plan, to calibrate at step 17. A 1v1 has no double
commit; a match without detected touches has none of this.
"""

from bisect import bisect_left
from collections import Counter, defaultdict
from dataclasses import dataclass

from rl_analysis import engagement
from rl_analysis.constants import Phase
from rl_analysis.frames import PerPlayer
from rl_analysis.match import Match
from rl_analysis.thresholds import (
    DOUBLE_COMMIT_MIN_OVERLAP,
    DOUBLE_COMMIT_PUNISH,
    DOUBLE_COMMIT_RESOLVE,
    KICKOFF_SCRAMBLE,
)


@dataclass(frozen=True)
class DoubleCommit:
    """`time_s`: when the two were first engaged together; `touch_s`: the touch that ended it."""

    time_s: float
    team: int
    players: tuple[int, ...]
    touch_s: float
    punished: bool


def _teams(match: Match) -> dict[int, int]:
    return {member["player_idx"]: member["team"] for member in match.events["roster"]}


def _scrambles(match: Match, touch_times: list[float]) -> list[tuple[float, float]]:
    """Each kickoff, from the end of its countdown to 2 s after its first touch."""
    ordered = match.frames.select("time_s", "phase").unique("time_s").sort("time_s").iter_rows()
    windows = []
    previous = None
    for time_s, phase in ordered:
        if phase == Phase.KICKOFF_WAITING and previous != Phase.KICKOFF_WAITING:
            index = bisect_left(touch_times, time_s)
            first = touch_times[index] if index < len(touch_times) else time_s
            windows.append((float(time_s), first + KICKOFF_SCRAMBLE.value))
        previous = phase
    return windows


def resolve(match: Match) -> list[DoubleCommit] | None:
    """The match's double commits, in time order; None without detected touches."""
    touches = match.events["touches"]
    if touches is None:
        return None
    teams = _teams(match)
    sizes = Counter(teams.values())
    touch_times = sorted(touch["time_s"] for touch in touches)
    scrambles = _scrambles(match, touch_times)
    threats = sorted(
        [
            (goal["time_s"], goal["team"])
            for goal in match.events["goals"]
            if goal["team"] is not None
        ]
        + [
            (event["time_s"], teams[event["player_idx"]])
            for event in match.events["stat_events"]
            if event["kind"] == "shot" and event["player_idx"] in teams
        ]
    )

    engaged_at: dict[int, dict[float, set[int]]] = {0: defaultdict(set), 1: defaultdict(set)}
    times: set[float] = set()
    for player, timeline in engagement.resolve(match).items():
        team = teams.get(player)
        for time_s, engaged in timeline:
            times.add(time_s)
            if engaged and team is not None:
                engaged_at[team][time_s].add(player)

    found = []
    ordered = sorted(times)
    for team in (0, 1):
        if sizes[team] < 2:
            continue
        start: float | None = None
        members: set[int] = set()
        for moment in [*ordered, None]:
            together = engaged_at[team].get(moment, set()) if moment is not None else set()
            if len(together) >= 2:
                if start is None:
                    start, members = moment, set(together)
                continue
            if start is not None:
                end = moment if moment is not None else ordered[-1]
                commit = _confirmed(start, end, team, members, touch_times, scrambles, threats)
                if commit is not None:
                    found.append(commit)
                start, members = None, set()
    return sorted(found, key=lambda commit: commit.time_s)


def _confirmed(
    start: float,
    end: float,
    team: int,
    members: set[int],
    touch_times: list[float],
    scrambles: list[tuple[float, float]],
    threats: list[tuple[float, int]],
) -> DoubleCommit | None:
    """An overlap of engaged teammates, from `start` to `end`, if it makes a double commit."""
    if end - start < DOUBLE_COMMIT_MIN_OVERLAP.value:
        return None
    if any(begin <= start <= until for begin, until in scrambles):
        return None
    index = bisect_left(touch_times, start)
    if index >= len(touch_times) or touch_times[index] > start + DOUBLE_COMMIT_RESOLVE.value:
        return None
    touch_s = touch_times[index]
    punished = any(
        scorer == 1 - team and touch_s < time_s <= touch_s + DOUBLE_COMMIT_PUNISH.value
        for time_s, scorer in threats
    )
    return DoubleCommit(start, team, tuple(sorted(members)), touch_s, punished)


def count(match: Match) -> PerPlayer:
    """`rot.double_commits`: double commits the player was part of: two teammates engaged on the
    ball together for 0.25 s, a touch ending it within 1.5 s, kickoffs aside. A count; None in 1v1
    and without detected touches."""
    commits = resolve(match)
    teams = _teams(match)
    sizes = Counter(teams.values())
    if commits is None:
        return dict.fromkeys(match.players)
    involved = Counter(player for commit in commits for player in commit.players)
    return {
        player: float(involved[player]) if sizes[teams.get(player, -1)] >= 2 else None
        for player in match.players
    }
