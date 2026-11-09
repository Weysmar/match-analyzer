"""Kickoffs (T13.1, T13.2), on frames and events made by hand. A countdown from 0 to 3 s, the cars
free from 3 s (the kickoff wait), live play from the first touch."""

from typing import Any

import pytest

from rl_analysis import kickoffs
from rl_analysis.constants import Phase

from .synthetic import frames, match_of, row

STEP_S = 0.5
END_S = 30.0
GO_S = 3.0
# Players 0 and 2 for blue, 1 and 3 for orange.
TEAM = {0: 0, 1: 1, 2: 0, 3: 1}
# The five kickoff spawns of blue (x, y); orange's are the same turned half a turn.
SPAWNS = {
    "diagonal_left": (-2048.0, -2560.0),
    "diagonal_right": (2048.0, -2560.0),
    "offset_left": (-256.0, -3840.0),
    "offset_right": (256.0, -3840.0),
    "center": (0.0, -4608.0),
}
KIND = {"diagonal": "diagonal", "offset": "center_offset", "center": "center"}


def phase_at(time_s: float, first_touch_s: float) -> Phase:
    if time_s < GO_S:
        return Phase.COUNTDOWN
    return Phase.KICKOFF_WAITING if time_s < first_touch_s else Phase.ACTIVE


def rows(first_touch_s: float, spawn: tuple[float, float] = (0.0, -4608.0)) -> list[dict[str, Any]]:
    out = []
    for index in range(round(END_S / STEP_S) + 1):
        time_s = index * STEP_S
        for player, team in TEAM.items():
            x, y = spawn if team == 0 else (-spawn[0], -spawn[1])
            out.append(
                row(
                    frame=index,
                    time_s=time_s,
                    dt_s=STEP_S,
                    phase=int(phase_at(time_s, first_touch_s)),
                    player_idx=player,
                    team=team,
                    x=x if player in (0, 1) else 0.0,
                    y=y if player in (0, 1) else 0.0,
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


def kickoff(
    first_touch_s: float,
    first_player: int,
    *,
    kind: str = "diagonal",
    winner: int | None = 0,
    goal: float | None = None,
) -> dict[str, Any]:
    return {
        "start_frame": 0,
        "start_time_s": 0.0,
        "end_frame": round((first_touch_s + 2) / STEP_S),
        "end_time_s": first_touch_s + 2,
        "kickoff_type": kind,
        "first_touch_frame": round(first_touch_s / STEP_S),
        "first_touch_time_s": first_touch_s,
        "first_touch_player_idx": first_player,
        "winner_team": winner,
        "outcome": "neutral" if winner is None else "win",
        "goal": goal is not None,
        "time_to_goal_s": goal,
        "takers": [],
    }


def goal_event(time_s: float, team: int, player: int) -> dict[str, Any]:
    return {
        "frame": round(time_s / STEP_S),
        "time_s": time_s,
        "team": team,
        "player_idx": player,
        "score_blue": int(team == 0),
        "score_orange": int(team == 1),
    }


def played(
    *touches: dict[str, Any], events: list[dict[str, Any]], first_touch_s: float = 5.0, **more: Any
) -> Any:
    return match_of(frames(*rows(first_touch_s)), touches=list(touches), kickoffs=events, **more)


def test_the_taker_is_the_first_of_the_team_to_touch() -> None:
    match = played(touch(5.0, 0), touch(5.5, 1), touch(6.0, 2), events=[kickoff(5.0, 0)])
    assert kickoffs.taken(match) == {0: 1.0, 1: 1.0, 2: 0.0, 3: 0.0}


def test_the_time_to_ball_runs_from_the_end_of_the_countdown() -> None:
    match = played(touch(5.0, 0), touch(5.5, 1), events=[kickoff(5.0, 0)])
    times = kickoffs.time_to_ball(match)
    assert times[0] == pytest.approx(5.0 - GO_S)
    assert times[1] == pytest.approx(5.5 - GO_S)
    assert times[2] is None


def test_a_team_that_does_not_touch_in_time_had_no_taker() -> None:
    """Over 6 s after the countdown, a touch is play, not the kickoff (`KICKOFF_TOUCH_MAX`)."""
    late = kickoff(5.0, 0)
    late["end_time_s"] = 20.0
    match = played(touch(5.0, 0), touch(GO_S + 6.5, 1), events=[late])
    assert kickoffs.taken(match)[1] == 0.0


def test_won_is_the_takers_team_winning_and_neutral_is_not_won() -> None:
    match = played(
        touch(5.0, 0),
        touch(5.5, 1),
        events=[kickoff(5.0, 0, winner=1)],
    )
    assert kickoffs.won_share(match) == {0: 0.0, 1: 100.0, 2: None, 3: None}
    neutral = played(touch(5.0, 0), touch(5.5, 1), events=[kickoff(5.0, 0, winner=None)])
    assert kickoffs.won_share(neutral)[0] == 0.0
    assert kickoffs.won_share(neutral)[1] == 0.0


def test_a_kickoff_goal_counts_against_the_team_that_conceded_it() -> None:
    match = played(
        touch(5.0, 0),
        touch(5.5, 1),
        events=[kickoff(5.0, 0, winner=1, goal=4.0)],
        goals=[goal_event(9.0, 1, 1)],
    )
    assert kickoffs.goals_conceded(match) == {0: 1.0, 1: 0.0}


def test_a_goal_long_after_the_kickoff_is_not_a_kickoff_goal() -> None:
    match = played(touch(5.0, 0), events=[kickoff(5.0, 0)], goals=[goal_event(25.0, 1, 1)])
    assert kickoffs.goals_conceded(match) == {0: 0.0, 1: 0.0}


def test_without_detections_nothing_is_known() -> None:
    no_kickoffs = played(touch(5.0, 0), events=[])
    assert kickoffs.taken(no_kickoffs) == {0: 0.0, 1: 0.0, 2: 0.0, 3: 0.0}
    for missing in ({"kickoffs": None}, {"touches": None}):
        match = match_of(frames(*rows(5.0)), **({"touches": [], "kickoffs": []} | missing))
        assert kickoffs.taken(match) == dict.fromkeys(TEAM)
        assert kickoffs.goals_conceded(match) == {0: None, 1: None}


@pytest.mark.parametrize("spawn", sorted(SPAWNS))
@pytest.mark.parametrize("taker_team", [0, 1])
def test_every_spawn_and_both_teams_are_read_alike(spawn: str, taker_team: int) -> None:
    """The five kickoff positions, blue's and orange's mirrored: the same metrics for the taker."""
    first, second = (0, 1) if taker_team == 0 else (1, 0)
    match = match_of(
        frames(*rows(5.0, SPAWNS[spawn])),
        touches=[touch(5.0, first), touch(5.4, second)],
        kickoffs=[kickoff(5.0, first, kind=KIND[spawn.split("_")[0]], winner=taker_team)],
    )
    assert kickoffs.taken(match)[first] == 1.0
    assert kickoffs.won_share(match)[first] == 100.0
    assert kickoffs.won_share(match)[second] == 0.0
    assert kickoffs.time_to_ball(match)[first] == pytest.approx(2.0)
    [resolved] = kickoffs.resolve(match) or []
    assert resolved.kind == KIND[spawn.split("_")[0]]
