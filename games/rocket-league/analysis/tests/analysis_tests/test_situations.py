"""The situations of a match (T13.4): turnovers, kickoffs and duels, in time order."""

from typing import Any

import pytest

from rl_analysis import situations
from rl_analysis.constants import Phase

from .synthetic import frames, match_of, row

STEP_S = 0.5
GO_S = 3.0
TEAM = {0: 0, 1: 1}


def rows(first_touch_s: float = 5.0, end_s: float = 30.0) -> list[dict[str, Any]]:
    out = []
    for index in range(round(end_s / STEP_S) + 1):
        time_s = index * STEP_S
        phase = (
            Phase.COUNTDOWN
            if time_s < GO_S
            else Phase.KICKOFF_WAITING
            if time_s < first_touch_s
            else Phase.ACTIVE
        )
        for player, team in TEAM.items():
            out.append(
                row(
                    frame=index,
                    time_s=time_s,
                    dt_s=STEP_S,
                    phase=int(phase),
                    player_idx=player,
                    team=team,
                )
            )
    return out


def touch(time_s: float, player: int) -> dict[str, Any]:
    return {
        "frame": round(time_s / STEP_S),
        "time_s": time_s,
        "player_idx": player,
        "team": TEAM[player],
        "ball_speed_change": 800.0,
        "kind": None,
        "height_band": None,
        "surface": None,
        "contested": False,
    }


KICKOFF = {
    "start_frame": 0,
    "start_time_s": 0.0,
    "end_frame": 14,
    "end_time_s": 7.0,
    "kickoff_type": "diagonal",
    "first_touch_frame": 10,
    "first_touch_time_s": 5.0,
    "first_touch_player_idx": 0,
    "winner_team": 1,
    "outcome": "win",
    "goal": False,
    "time_to_goal_s": None,
    "takers": [],
}
DUEL = {
    "start_frame": 10,
    "start_time_s": 5.0,
    "resolve_frame": 11,
    "resolve_time_s": 5.4,
    "is_kickoff": True,
    "blue_player_idx": 0,
    "orange_player_idx": 1,
    "winner_team": 0,
    "possession_team": 1,
}
# Blue holds the ball, orange takes it: one turnover at 12 s.
TOUCHES = [
    touch(5.0, 0),
    touch(5.4, 1),
    touch(10.0, 0),
    touch(11.0, 0),
    touch(12.0, 1),
    touch(13.0, 1),
]


def detected(**events: Any) -> list[situations.Situation]:
    found = situations.detect(match_of(frames(*rows()), **events))
    assert found is not None
    return found


def test_a_match_lists_its_turnovers_kickoffs_and_duels_in_time_order() -> None:
    found = detected(touches=TOUCHES, kickoffs=[KICKOFF], fifty_fifties=[DUEL])
    assert [(s.kind, s.time_s) for s in found] == [
        ("kickoff", GO_S),
        ("fifty_fifty", 5.0),
        ("turnover", 12.0),
    ]


def test_a_kickoff_is_at_the_end_of_the_countdown_with_its_winner_and_takers() -> None:
    [kickoff] = [s for s in detected(touches=TOUCHES, kickoffs=[KICKOFF]) if s.kind == "kickoff"]
    assert (kickoff.team, kickoff.players) == (1, (0, 1))
    assert kickoff.details == {"kickoff_type": "diagonal", "goal": False}
    assert kickoff.clock_s == 0.0


def test_a_duel_belongs_to_the_team_with_the_ball_afterwards() -> None:
    [duel] = [s for s in detected(touches=TOUCHES, fifty_fifties=[DUEL]) if s.kind == "fifty_fifty"]
    assert (duel.team, duel.players) == (1, (0, 1))
    assert duel.details == {"is_kickoff": True, "contact_winner": 0}


def test_a_turnover_names_who_took_then_who_lost_and_its_clock() -> None:
    [turnover] = [s for s in detected(touches=TOUCHES) if s.kind == "turnover"]
    assert (turnover.team, turnover.players) == (1, (1, 0))
    # Live play from the first touch at 5 s: the clock at the end of the frame at 12 s.
    assert turnover.clock_s == pytest.approx(7.5)


def test_without_touches_there_is_no_situation_to_tell() -> None:
    assert situations.detect(match_of(frames(*rows()), touches=None, kickoffs=[KICKOFF])) is None


def test_a_detection_the_parser_did_not_run_is_left_out() -> None:
    found = detected(touches=TOUCHES, kickoffs=None, fifty_fifties=None)
    assert {s.kind for s in found} == {"turnover"}


GOAL = {"frame": 28, "time_s": 14.0, "team": 1, "player_idx": 1, "score_blue": 0, "score_orange": 1}


def test_a_goal_conceded_is_a_situation_with_its_tags_and_facts() -> None:
    [context] = [s for s in detected(touches=TOUCHES, goals=[GOAL]) if s.kind == "goal_context"]
    # Blue conceded; its only player stood at the center, 5120 uu from its goal.
    assert (context.time_s, context.team, context.players) == (14.0, 0, (0,))
    assert context.tags == ("last_back_far",)
    # Live play from 5 s: 9.5 s of play at the goal, the kickoff wait from 3 s in the window.
    assert context.clock_s == 9.5
    assert context.details == {
        "window_s": 9.5,
        "shot_clock_s": 8.5,
        "last_touch": {"player": 1, "team": 1},
        "lost_ball": {
            "player": 0,
            "clock_s": 7.5,
            "before_goal_s": 2.0,
            "ball_y": 0.0,
            "roles": [],
        },
        "defenders": [
            {
                "player": 0,
                "goal_distance": 5120.0,
                "boost": 50.0,
                "demolished": False,
                "last_back": True,
            }
        ],
    }


def test_players_in_details_become_match_player_ids() -> None:
    details = {"player": 0, "roles": [{"player": 1, "role": "first"}, {"player": 9}], "team": 1}
    assert situations.with_ids(details, {0: 40, 1: 41}) == {
        "player": 40,
        "roles": [{"player": 41, "role": "first"}, {"player": None}],
        "team": 1,
    }
