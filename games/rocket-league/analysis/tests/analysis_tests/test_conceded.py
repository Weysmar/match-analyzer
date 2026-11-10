"""Goals conceded (T15.1, T15.2), on frames made by hand: frames every 0.25 s (exact in binary, so
the clock adds up exactly), blue (players 0 and 1) conceding to orange (players 2 and 3)."""

from collections.abc import Callable
from typing import Any

import pytest

from rl_analysis import commits, conceded, overcommits
from rl_analysis.commits import DoubleCommit
from rl_analysis.constants import Phase
from rl_analysis.overcommits import Overcommit

from .synthetic import frames, match_of, row

DT = 0.25
TEAM = {0: 0, 1: 0, 2: 1, 3: 1}
# Blue's goal is at y = -5120: player 0 is 1120 uu from it, player 1 4120 uu.
HOME = {0: -4000.0, 1: -1000.0, 2: 1000.0, 3: 2000.0}
LIVE = [(0.0, Phase.ACTIVE)]
KICKOFF = [(0.0, Phase.COUNTDOWN), (3.0, Phase.KICKOFF_WAITING), (4.0, Phase.ACTIVE)]


def touch(time_s: float, player: int) -> dict[str, Any]:
    return {
        "frame": round(time_s / DT),
        "time_s": time_s,
        "player_idx": player,
        "team": TEAM[player],
        "ball_speed_change": 500.0,
        "kind": None,
        "height_band": None,
        "surface": None,
        "contested": False,
    }


def goal(time_s: float, team: int = 1, player: int | None = 2) -> dict[str, Any]:
    return {
        "frame": round(time_s / DT),
        "time_s": time_s,
        "team": team,
        "player_idx": player,
        "score_blue": None,
        "score_orange": None,
    }


def played(
    goal_s: float,
    touches: list[dict[str, Any]] | None,
    *,
    phases: list[tuple[float, Phase]] = LIVE,
    y: Callable[[int, float], float] = lambda player, _t: HOME[player],
    boost: Callable[[int, float], float] = lambda _p, _t: 50.0,
    ball_y: float = 0.0,
    **events: Any,
) -> Any:
    """Frames from 0 to the goal, which orange scores at `goal_s` unless `goals` says otherwise."""
    rows = []
    for index in range(round(goal_s / DT) + 1):
        time_s = index * DT
        phase = [p for start, p in phases if start <= time_s][-1]
        rows += [
            row(
                frame=index,
                time_s=time_s,
                dt_s=0.0 if index == 0 else DT,
                phase=int(phase),
                ball_y=ball_y,
                player_idx=player,
                team=team,
                y=y(player, time_s),
                boost=boost(player, time_s),
            )
            for player, team in TEAM.items()
        ]
    return match_of(frames(*rows), **({"touches": touches, "goals": [goal(goal_s)]} | events))


def only(match: Any) -> conceded.GoalContext:
    found = conceded.resolve(match)
    assert found is not None
    assert len(found) == 1
    return found[0]


def test_the_window_is_the_last_ten_seconds_of_play() -> None:
    context = only(played(15.0, [touch(14.0, 2)]))
    # The clock at the goal is 15 s; the frame ending at 5 s is the last one outside the window.
    assert (context.team, context.window_start_s, context.window_s) == (0, 5.25, 10.0)
    assert context.clock_s == 15.0


def test_the_window_stops_at_the_countdown_and_keeps_the_kickoff_wait() -> None:
    context = only(played(8.0, [touch(4.0, 2)], phases=KICKOFF))
    # Live from 4 s: 17 frames of 0.25 s, the first one counting the time since the countdown.
    assert (context.window_start_s, context.window_s) == (3.0, 4.25)


def test_an_overtime_goal_never_looks_back_into_regulation_time() -> None:
    phases = [(0.0, Phase.ACTIVE), (10.0, Phase.COUNTDOWN), (13.0, Phase.ACTIVE)]
    context = only(played(16.0, [touch(5.0, 0), touch(15.0, 2)], phases=phases))
    assert (context.window_start_s, context.window_s) == (13.0, 3.25)
    assert context.last_touch == 2


def test_the_shot_is_the_scorers_last_touch_and_a_deflection_is_an_own_touch() -> None:
    context = only(played(6.0, [touch(4.0, 3), touch(5.0, 2), touch(5.5, 0)]))
    assert (context.shot_s, context.last_touch, context.last_touch_team) == (5.0, 0, 0)
    assert "own_touch_last" in context.tags


def test_an_own_goal_takes_the_last_touch_as_the_shot() -> None:
    context = only(played(6.0, [touch(5.0, 1)]))
    assert (context.shot_s, context.last_touch) == (5.0, 1)
    assert "own_touch_last" in context.tags


def test_without_a_touch_the_shot_is_the_goal() -> None:
    context = only(played(6.0, []))
    assert (context.shot_s, context.last_touch, context.lost_ball) == (6.0, None, None)
    assert context.tags == ()


def test_a_clean_goal_has_no_tag_and_its_facts() -> None:
    context = only(played(6.0, [touch(5.0, 2)]))
    assert context.tags == ()
    assert context.last_back == 0
    assert [(d.player, d.goal_distance, d.boost, d.demolished) for d in context.defenders] == [
        (0, 1120.0, 50.0, False),
        (1, 4120.0, 50.0, False),
    ]


def test_a_lost_ball_in_the_own_half_with_the_roles_then() -> None:
    touches = [touch(1.0, 0), touch(2.0, 0), touch(3.0, 2), touch(3.5, 2), touch(5.0, 2)]
    context = only(played(8.0, touches, ball_y=-2000.0))
    lost = context.lost_ball
    assert lost is not None
    # Orange took the ball at its first touch, 5 s of play before the goal.
    assert (lost.time_s, lost.before_goal_s, lost.lost_by, lost.ball_y) == (3.0, 5.0, 0, -2000.0)
    # Player 1 is 1000 uu from the ball, player 0 2000 uu: the first man is player 1.
    assert lost.roles == {0: "second", 1: "first"}
    assert "turnover_own_half" in context.tags


def test_a_lost_ball_in_the_opponents_half_is_no_tag() -> None:
    touches = [touch(1.0, 0), touch(2.0, 0), touch(3.0, 2), touch(3.5, 2), touch(5.0, 2)]
    context = only(played(8.0, touches, ball_y=2000.0))
    assert context.lost_ball is not None
    assert context.lost_ball.ball_y == 2000.0
    assert "turnover_own_half" not in context.tags


def test_a_lost_ball_before_the_window_is_not_in_the_context() -> None:
    touches = [touch(1.0, 0), touch(2.0, 0), touch(3.0, 2), touch(3.5, 2), touch(14.5, 2)]
    context = only(played(15.0, touches, ball_y=-2000.0))
    assert context.lost_ball is None


def test_the_last_defender_far_and_short_of_boost() -> None:
    def far(player: int, _t: float) -> float:
        return {0: -2000.0, 1: 0.0}.get(player, HOME[player])

    context = only(played(6.0, [touch(5.0, 2)], y=far, boost=lambda p, _t: 10.0 if p == 0 else 90))
    assert context.last_back == 0
    assert {"last_back_far", "last_back_low_boost"} <= set(context.tags)


def test_the_last_defender_at_2000_uu_with_20_boost_is_neither() -> None:
    def edge(player: int, _t: float) -> float:
        return {0: -3120.0, 1: 0.0}.get(player, HOME[player])

    context = only(played(6.0, [touch(5.0, 2)], y=edge, boost=lambda _p, _t: 20.0))
    assert context.tags == ()


def demolition(time_s: float, victim: int) -> dict[str, Any]:
    return {
        "frame": round(time_s / DT),
        "time_s": time_s,
        "attacker_idx": 2,
        "victim_idx": victim,
        "x": 0.0,
        "y": 0.0,
        "z": 17.0,
    }


@pytest.mark.parametrize(
    ("at", "victim", "tagged"), [(4.0, 0, True), (2.5, 0, False), (4.0, 3, False)]
)
def test_a_defender_demolished_within_three_seconds(at: float, victim: int, tagged: bool) -> None:
    context = only(played(6.0, [touch(5.0, 2)], demolitions=[demolition(at, victim)]))
    assert ("defender_demolished" in context.tags) is tagged


def beaten(time_s: float, player: int) -> dict[str, Any]:
    return {
        "frame": round(time_s / DT),
        "time_s": time_s,
        "player_idx": player,
        "winner_idx": 2,
        "team": TEAM[player],
        "distance_at_touch": 300.0,
        "margin_s": 0.2,
        "approach_speed": 900.0,
    }


@pytest.mark.parametrize(
    ("at", "player", "tagged"), [(3.0, 1, True), (1.5, 1, False), (3.0, 2, False)]
)
def test_a_defender_beaten_to_the_ball_within_three_seconds_of_the_shot(
    at: float, player: int, tagged: bool
) -> None:
    context = only(played(6.0, [touch(5.0, 2)], beaten_to_ball=[beaten(at, player)]))
    assert ("beaten_to_ball" in context.tags) is tagged


def test_a_kickoff_goal() -> None:
    kickoff = {
        "start_frame": 0,
        "start_time_s": 0.0,
        "end_frame": 18,
        "end_time_s": 4.5,
        "kickoff_type": "center",
        "first_touch_frame": 16,
        "first_touch_time_s": 4.0,
        "first_touch_player_idx": 2,
        "winner_team": 1,
        "outcome": "win",
        "goal": True,
        "time_to_goal_s": 4.0,
        "takers": [],
    }
    context = only(played(8.0, [touch(4.0, 2)], phases=KICKOFF, kickoffs=[kickoff]))
    assert "kickoff_goal" in context.tags


@pytest.mark.parametrize(("start", "tagged"), [(4.0, True), (0.5, True), (-2.0, False)])
def test_a_double_commit_overlapping_the_window(
    monkeypatch: pytest.MonkeyPatch, start: float, tagged: bool
) -> None:
    # The window of a goal at 12 s starts at 2.25 s; a commit from 0.5 s to 2.5 s overlaps it.
    commit = DoubleCommit(start, 0, (0, 1), start + 2.0, punished=True)
    monkeypatch.setattr(commits, "resolve", lambda _match: [commit])
    context = only(played(12.0, [touch(11.0, 2)]))
    assert ("double_commit" in context.tags) is tagged


def test_an_overcommit_counts_only_for_the_team_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    found = [Overcommit(4.0, 1, (2, 3), 1.5)]
    monkeypatch.setattr(overcommits, "resolve", lambda _match: found)
    assert "overcommit" not in only(played(6.0, [touch(5.0, 2)])).tags
    found[0] = Overcommit(4.0, 0, (0, 1), 1.5)
    assert "overcommit" in only(played(6.0, [touch(5.0, 2)])).tags


def test_both_teams_concede_in_one_match() -> None:
    match = played(10.0, [touch(4.0, 0), touch(9.0, 2)], goals=[goal(5.0, 0, 0), goal(10.0)])
    found = conceded.resolve(match)
    assert found is not None
    assert [(c.goal, c.team, c.shot_s) for c in found] == [(0, 1, 4.0), (1, 0, 9.0)]


def test_without_detected_touches_there_is_no_context() -> None:
    assert conceded.resolve(played(6.0, None)) is None


def test_every_tag_is_listed_once() -> None:
    assert len(set(conceded.TAGS)) == len(conceded.TAGS) == 9
