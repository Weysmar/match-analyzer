"""Goals conceded (T15.1 and T15.2 of docs/PLAN-V2.md, section 5.5): the context of each goal, the
facts of the play before it, and tags that say which of the usual causes were there.

The window is the last `GOAL_CONTEXT_WINDOW` (10 s) of the game clock before the goal. The clock
only runs in live play, and the window never reaches back past the countdown that started the play:
a goal 4 s after a kickoff has those 4 s and the kickoff wait before them, and an overtime goal
never looks back into regulation time.

The shot is the scoring team's last touch before the goal, within the window; the last touch of
anyone when the scoring team made none there (an own goal); the goal itself without any touch.

Facts, shown without judgment:

- the last touch before the goal, and its team;
- the conceding team's last lost possession in the window (`possession`): where the ball was, how
  many seconds of play before the goal, and the team's rotation roles then;
- each defender at the shot: distance to their own goal on the ground plane, boost, demolished or
  not; the last defender is the one closest to their own goal.

Tags, each a fact that holds or not:

- `double_commit`: a double commit of the team (`commits`) overlaps the window;
- `overcommit`: an overcommit of the team (`overcommits`) overlaps the window;
- `turnover_own_half`: the team's last lost possession in the window was in its own half;
- `beaten_to_ball`: a defender, going for the ball, was beaten to it (subtr-actor's
  `beaten_to_ball`) within `BEATEN_BEFORE_SHOT` (3 s) before the shot;
- `last_back_far`: the last defender stands more than `LAST_BACK_FAR` (2000 uu) from their goal at
  the shot;
- `last_back_low_boost`: the last defender has less than `LAST_BACK_LOW_BOOST` (20) boost at the
  shot;
- `defender_demolished`: a defender was demolished within `DEMOLISHED_BEFORE_GOAL` (3 s) before
  the goal;
- `kickoff_goal`: subtr-actor's kickoff goal, within 12 s of a kickoff (`kickoffs`);
- `own_touch_last`: the last touch before the goal came from the conceding team.

Players are `player_idx`; no name, no platform id. A match without detected touches has no context.
"""

import math
from bisect import bisect_right
from dataclasses import dataclass

import polars as pl

from ma_schemas.types import Goal
from rl_analysis import clock, commits, kickoffs, overcommits, possession, rotation
from rl_analysis.constants import BLUE_TEAM, FIELD_HALF_LENGTH, Phase
from rl_analysis.match import Match
from rl_analysis.thresholds import (
    BEATEN_BEFORE_SHOT,
    DEMOLISHED_BEFORE_GOAL,
    GOAL_CONTEXT_WINDOW,
    LAST_BACK_FAR,
    LAST_BACK_LOW_BOOST,
)

TAGS = (
    "double_commit",
    "overcommit",
    "turnover_own_half",
    "beaten_to_ball",
    "last_back_far",
    "last_back_low_boost",
    "defender_demolished",
    "kickoff_goal",
    "own_touch_last",
)
# The play a window may cover: live play and the kickoff wait, which the clock does not count.
_PLAY = (Phase.KICKOFF_WAITING, Phase.ACTIVE)


@dataclass(frozen=True)
class Defender:
    """A player of the conceding team at the shot. Away or demolished, no distance nor boost."""

    player: int
    goal_distance: float | None
    boost: float | None
    demolished: bool


@dataclass(frozen=True)
class LostBall:
    """The conceding team's last lost possession in the window. `ball_y` is seen by the team:
    negative in its own half. `roles`: its players' rotation roles then, by `player_idx`."""

    time_s: float
    before_goal_s: float | None
    lost_by: int | None
    ball_y: float | None
    roles: dict[int, str]


@dataclass(frozen=True)
class GoalContext:
    """`goal`: the index of the goal in `events["goals"]`; `team`: the team that conceded it.
    Times are the replay's; `clock_s` and `window_s` are seconds of play."""

    goal: int
    time_s: float
    team: int
    clock_s: float | None
    window_start_s: float
    window_s: float
    shot_s: float
    last_touch: int | None
    last_touch_team: int | None
    lost_ball: LostBall | None
    defenders: tuple[Defender, ...]
    last_back: int | None
    tags: tuple[str, ...]


@dataclass(frozen=True)
class _Timeline:
    """One row per frame, in time order: its number, time, phase and the clock at its end."""

    frames: list[int]
    times: list[float]
    phases: list[int]
    clocks: list[float]

    def row_of_frame(self, frame: int) -> int:
        return bisect_right(self.frames, frame) - 1

    def clock_at(self, time_s: float) -> float | None:
        row = bisect_right(self.times, time_s) - 1
        return None if row < 0 else self.clocks[row]

    def window_start(self, row: int) -> tuple[int, float]:
        """The first row of the window that ends with `row`, and the seconds of play it covers: the
        frames that end less than the window's length of play before it."""
        start = row
        while (
            start > 0
            and self.phases[start - 1] in _PLAY
            and self.clocks[row] - self.clocks[start - 1] < GOAL_CONTEXT_WINDOW.value
        ):
            start -= 1
        before = self.clocks[start - 1] if start > 0 else 0.0
        return start, self.clocks[row] - before


def _timeline(match: Match) -> _Timeline:
    per_frame = clock.per_frame(match.frames).join(
        match.frames.group_by("frame").agg(pl.col("time_s").first()), on="frame"
    )
    ordered = per_frame.sort("frame")
    return _Timeline(
        ordered["frame"].to_list(),
        ordered["time_s"].to_list(),
        ordered["phase"].to_list(),
        ordered["clock"].to_list(),
    )


def _own_goal_y(team: int) -> float:
    return -FIELD_HALF_LENGTH if team == BLUE_TEAM else FIELD_HALF_LENGTH


def _seen_by(team: int, y: float) -> float:
    """`y` as seen by the team: positive towards the goal it attacks."""
    return y if team == BLUE_TEAM else -y


def _rows_at(frames: pl.DataFrame, time_s: float) -> pl.DataFrame:
    """Every player's row of the last frame at or before `time_s`."""
    before = frames.filter(pl.col("time_s") <= time_s)
    if before.height == 0:
        return before
    return before.filter(pl.col("frame") == before["frame"].max())


def _defenders(frames: pl.DataFrame, team: int, shot_s: float) -> tuple[Defender, ...]:
    rows = _rows_at(frames, shot_s).filter(pl.col("team") == team).sort("player_idx")
    found = []
    goal_y = _own_goal_y(team)
    for player, present, demolished, x, y, boost in rows.select(
        "player_idx", "present", "demolished", "x", "y", "boost"
    ).iter_rows():
        on_field = present and not demolished and x is not None and y is not None
        found.append(
            Defender(
                int(player),
                math.hypot(x, y - goal_y) if on_field else None,
                float(boost) if on_field and boost is not None else None,
                bool(demolished),
            )
        )
    return tuple(found)


def _last_back(defenders: tuple[Defender, ...]) -> Defender | None:
    """The defender closest to their own goal, on the field."""
    on_field = [d for d in defenders if d.goal_distance is not None]
    return min(on_field, key=lambda d: (d.goal_distance, d.player)) if on_field else None


def _overlaps(intervals: list[tuple[float, float]], start_s: float, end_s: float) -> bool:
    return any(begin <= end_s and until >= start_s for begin, until in intervals)


def _within(times: list[float], start_s: float, end_s: float) -> bool:
    return any(start_s <= time_s <= end_s for time_s in times)


@dataclass(frozen=True)
class _Detections:
    """What the tags read, computed once for the match."""

    teams: dict[int, int]
    touches: list[tuple[float, int, int]]
    turnovers: tuple[possession.Turnover, ...]
    commits: list[commits.DoubleCommit]
    overcommits: list[overcommits.Overcommit]
    kickoff_goals: set[float]


def _detections(match: Match, resolved: possession.Possession) -> _Detections:
    touches = match.events["touches"] or []
    return _Detections(
        teams={member["player_idx"]: member["team"] for member in match.events["roster"]},
        touches=sorted((t["time_s"], t["team"], t["player_idx"]) for t in touches),
        turnovers=resolved.turnovers,
        commits=commits.resolve(match) or [],
        overcommits=overcommits.resolve(match) or [],
        kickoff_goals={k.goal_s for k in kickoffs.resolve(match) or [] if k.goal_s is not None},
    )


def resolve(match: Match) -> list[GoalContext] | None:
    """The context of every goal of the match, in the order of `events["goals"]`; None without
    detected touches. A goal before any frame has none."""
    resolved = possession.resolve(match)
    if resolved is None:
        return None
    timeline = _timeline(match)
    found = _detections(match, resolved)
    windows: list[tuple[int, Goal, int, float]] = []
    lost: dict[int, possession.Turnover] = {}
    for index, goal in enumerate(match.events["goals"]):
        row = timeline.row_of_frame(goal["frame"])
        if row < 0:
            continue
        start, window_s = timeline.window_start(row)
        windows.append((index, goal, start, window_s))
        mine = [
            turnover
            for turnover in found.turnovers
            if turnover.team == goal["team"]
            and timeline.times[start] <= turnover.time_s <= goal["time_s"]
        ]
        if mine:
            lost[index] = mine[-1]
    roles = rotation.resolve(match, at=[turnover.time_s for turnover in lost.values()]).at
    return [
        _context(match, timeline, found, index, goal, start, window_s, lost.get(index), roles)
        for index, goal, start, window_s in windows
    ]


def _context(
    match: Match,
    timeline: _Timeline,
    found: _Detections,
    index: int,
    goal: Goal,
    start: int,
    window_s: float,
    turnover: possession.Turnover | None,
    roles: dict[float, dict[int, rotation.Role]],
) -> GoalContext:
    """One goal's context, its window starting at row `start` of the timeline."""
    team = 1 - goal["team"]
    window_start_s, goal_s = timeline.times[start], goal["time_s"]
    in_window = [touch for touch in found.touches if window_start_s <= touch[0] <= goal_s]
    scorers = [touch for touch in in_window if touch[1] == goal["team"]]
    shot_s = (scorers or in_window)[-1][0] if in_window else goal_s
    last = in_window[-1] if in_window else None
    defenders = _defenders(match.frames, team, shot_s)
    last_back = _last_back(defenders)
    lost_ball = (
        None if turnover is None else _lost_ball(match, timeline, team, goal_s, turnover, roles)
    )

    def mine(player: int | None) -> bool:
        return player is not None and found.teams.get(player) == team

    tags = {
        "double_commit": _overlaps(
            [(c.time_s, c.touch_s) for c in found.commits if c.team == team], window_start_s, goal_s
        ),
        "overcommit": _overlaps(
            [(o.time_s, o.time_s + o.duration_s) for o in found.overcommits if o.team == team],
            window_start_s,
            goal_s,
        ),
        "turnover_own_half": lost_ball is not None
        and lost_ball.ball_y is not None
        and lost_ball.ball_y < 0,
        "beaten_to_ball": _within(
            [b["time_s"] for b in match.events["beaten_to_ball"] or [] if mine(b["player_idx"])],
            shot_s - BEATEN_BEFORE_SHOT.value,
            shot_s,
        ),
        "last_back_far": last_back is not None
        and last_back.goal_distance is not None
        and last_back.goal_distance > LAST_BACK_FAR.value,
        "last_back_low_boost": last_back is not None
        and last_back.boost is not None
        and last_back.boost < LAST_BACK_LOW_BOOST.value,
        "defender_demolished": _within(
            [d["time_s"] for d in match.events["demolitions"] if mine(d["victim_idx"])],
            goal_s - DEMOLISHED_BEFORE_GOAL.value,
            goal_s,
        ),
        "kickoff_goal": goal_s in found.kickoff_goals,
        "own_touch_last": last is not None and last[1] == team,
    }
    return GoalContext(
        goal=index,
        time_s=goal_s,
        team=team,
        clock_s=timeline.clock_at(goal_s),
        window_start_s=window_start_s,
        window_s=window_s,
        shot_s=shot_s,
        last_touch=None if last is None else last[2],
        last_touch_team=None if last is None else last[1],
        lost_ball=lost_ball,
        defenders=defenders,
        last_back=None if last_back is None else last_back.player,
        tags=tuple(tag for tag in TAGS if tags[tag]),
    )


def _lost_ball(
    match: Match,
    timeline: _Timeline,
    team: int,
    goal_s: float,
    turnover: possession.Turnover,
    roles: dict[float, dict[int, rotation.Role]],
) -> LostBall:
    ball = _rows_at(match.frames, turnover.time_s)["ball_y"]
    ball_y = None if ball.len() == 0 or ball[0] is None else _seen_by(team, float(ball[0]))
    at_goal, at_turnover = timeline.clock_at(goal_s), timeline.clock_at(turnover.time_s)
    then = roles.get(turnover.time_s, {})
    teams = {member["player_idx"]: member["team"] for member in match.events["roster"]}
    return LostBall(
        time_s=turnover.time_s,
        before_goal_s=None if at_goal is None or at_turnover is None else at_goal - at_turnover,
        lost_by=turnover.lost_by,
        ball_y=ball_y,
        roles={
            player: role.value for player, role in sorted(then.items()) if teams.get(player) == team
        },
    )
