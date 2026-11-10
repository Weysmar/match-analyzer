"""Overcommits (T14.4 of docs/PLAN-V2.md, section 5.4).

While the opponents hold the ball, as `possession` resolves it, every player of the team is ahead of
it: their relative `y`, towards the goal they attack, beyond the ball's by more than
`OVERCOMMIT_MARGIN` (150 uu, subtr-actor's level-with-the-ball margin), for at least
`OVERCOMMIT_MIN` (1 s, the plan's convention). Nobody is left between the ball and the goal.

The team must be whole on the field: a demolished teammate, respawning at home, is not ahead. A 1v1
has no overcommit in this sense; a match without detected touches has none of this.

The plan's variant, subtr-actor's outnumbered attack (`rush`), is measured beside it on the corpus
(B21 of the plan), not computed here: the parser does not emit it.
"""

from bisect import bisect_right
from collections import Counter
from dataclasses import dataclass
from itertools import groupby

from rl_analysis import possession
from rl_analysis.constants import BLUE_TEAM, Phase
from rl_analysis.match import Match
from rl_analysis.possession import TEAMS, PerTeam, Segment
from rl_analysis.thresholds import OVERCOMMIT_MARGIN, OVERCOMMIT_MIN


@dataclass(frozen=True)
class Overcommit:
    """`time_s`: when the whole team got ahead of the ball; `duration_s`: how long it stayed."""

    time_s: float
    team: int
    players: tuple[int, ...]
    duration_s: float


def _holder(segments: list[Segment], starts: list[float], time_s: float) -> int | None:
    """The team holding the ball at `time_s`, or None when it is loose."""
    index = bisect_right(starts, time_s) - 1
    if index < 0:
        return None
    segment = segments[index]
    return segment.team if segment.start_s <= time_s < segment.end_s else None


def resolve(match: Match) -> list[Overcommit] | None:
    """The match's overcommits, in time order; None without detected touches."""
    resolved = possession.resolve(match)
    if resolved is None:
        return None
    held = [segment for segment in resolved.segments if segment.team is not None]
    starts = [segment.start_s for segment in held]
    sizes: Counter[int] = Counter(int(member["team"]) for member in match.events["roster"])

    rows = (
        match.frames.select(
            "time_s", "phase", "ball_y", "player_idx", "team", "present", "demolished", "y"
        )
        .sort("time_s", "player_idx")
        .iter_rows()
    )
    found: list[Overcommit] = []
    open_since: dict[int, tuple[float, tuple[int, ...]] | None] = dict.fromkeys(TEAMS)
    last_time = 0.0

    def close(team: int, now: float) -> None:
        opened = open_since[team]
        if opened is not None and now - opened[0] >= OVERCOMMIT_MIN.value:
            found.append(Overcommit(opened[0], team, opened[1], now - opened[0]))
        open_since[team] = None

    for time_s, grouped in groupby(rows, key=lambda row: row[0]):
        players = list(grouped)
        last_time = float(time_s)
        phase, ball_y = players[0][1], players[0][2]
        holder = _holder(held, starts, last_time)
        for team in TEAMS:
            members = [row for row in players if row[4] == team]
            ahead = (
                phase == Phase.ACTIVE
                and ball_y is not None
                and holder == 1 - team
                and sizes[team] >= 2
                and len(members) == sizes[team]
                and all(_ahead(row, team, float(ball_y)) for row in members)
            )
            if ahead and open_since[team] is None:
                open_since[team] = (last_time, tuple(int(row[3]) for row in members))
            elif not ahead:
                close(team, last_time)
    for team in TEAMS:
        close(team, last_time)
    return sorted(found, key=lambda overcommit: overcommit.time_s)


def _ahead(row: tuple[object, ...], team: int, ball_y: float) -> bool:
    """A car on the field, beyond the ball towards the goal its team attacks."""
    present, demolished, y = row[5], row[6], row[7]
    if not present or demolished or y is None:
        return False
    sign = 1.0 if team == BLUE_TEAM else -1.0
    return sign * (float(y) - ball_y) > OVERCOMMIT_MARGIN.value  # type: ignore[arg-type]


def count(match: Match) -> PerTeam:
    """`rot.overcommits`: times the whole team was ahead of the ball by more than 150 uu for at
    least 1 s, while the opponents held it. A count; None in 1v1 and without detected touches."""
    found = resolve(match)
    sizes: Counter[int] = Counter(int(member["team"]) for member in match.events["roster"])
    if found is None:
        return dict.fromkeys(TEAMS)
    times = Counter(overcommit.team for overcommit in found)
    return {team: float(times[team]) if sizes[team] >= 2 else None for team in TEAMS}
