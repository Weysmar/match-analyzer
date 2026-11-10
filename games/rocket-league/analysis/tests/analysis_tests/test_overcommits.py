"""Overcommits (T14.4), on frames made by hand: the ball at the center, frames every 0.05 s, and
orange holding the ball from 1 s to 4 s (touches every second)."""

from collections.abc import Callable
from typing import Any

import pytest

from rl_analysis import overcommits

from .synthetic import frames, match_of, row

DT = 0.05
COUNT = 120
# Players 0 and 1 for blue (attacking +y), 2 and 3 for orange (attacking -y).
TEAM = {0: 0, 1: 0, 2: 1, 3: 1}
# Where a car stands along y at a frame index.
Placement = Callable[[int], float]


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


ORANGE_HOLDS = [touch(t, 2) for t in (1.0, 2.0, 3.0, 4.0)]
BLUE_HOLDS = [touch(t, 0) for t in (1.0, 2.0, 3.0, 4.0)]


def between(start_s: float, end_s: float, inside: float, outside: float) -> Placement:
    return lambda index: inside if start_s <= index * DT < end_s else outside


def at(y: float) -> Placement:
    return lambda _index: y


def played(
    places: dict[int, Placement],
    touches: list[dict[str, Any]] | None = ORANGE_HOLDS,
    *,
    teams: dict[int, int] = TEAM,
    demolished: Callable[[int, int], bool] = lambda _p, _i: False,
) -> Any:
    rows = [
        row(
            frame=index,
            time_s=index * DT,
            dt_s=0.0 if index == 0 else DT,
            player_idx=player,
            team=team,
            y=places[player](index),
            demolished=demolished(player, index),
        )
        for index in range(COUNT)
        for player, team in teams.items()
    ]
    return match_of(frames(*rows), touches=touches)


# Orange's cars behind the ball for them (y > 0), out of the question.
ORANGE_HOME = {2: at(1000.0), 3: at(2000.0)}


def test_the_whole_team_ahead_for_a_second_while_the_opponents_hold_it() -> None:
    match = played(
        {0: between(1.5, 3.0, 600.0, -800.0), 1: between(1.5, 3.0, 400.0, -2000.0)} | ORANGE_HOME
    )
    [found] = overcommits.resolve(match) or []
    assert (found.team, found.players) == (0, (0, 1))
    assert found.time_s == pytest.approx(1.5)
    assert found.duration_s == pytest.approx(1.5)
    assert overcommits.count(match) == {0: 1.0, 1: 0.0}


def test_one_player_back_is_no_overcommit() -> None:
    match = played({0: between(1.5, 3.0, 600.0, -800.0), 1: at(-2000.0)} | ORANGE_HOME)
    assert overcommits.resolve(match) == []


def test_ahead_by_150_uu_or_less_is_level_not_ahead() -> None:
    match = played(
        {0: between(1.5, 3.0, 600.0, -800.0), 1: between(1.5, 3.0, 150.0, -2000.0)} | ORANGE_HOME
    )
    assert overcommits.resolve(match) == []


def test_less_than_a_second_is_no_overcommit() -> None:
    match = played(
        {0: between(1.5, 2.4, 600.0, -800.0), 1: between(1.5, 2.4, 400.0, -2000.0)} | ORANGE_HOME
    )
    assert overcommits.resolve(match) == []


def test_ahead_with_the_ball_is_attacking_not_overcommitting() -> None:
    match = played(
        {0: between(1.5, 3.0, 600.0, -800.0), 1: between(1.5, 3.0, 400.0, -2000.0)} | ORANGE_HOME,
        BLUE_HOLDS,
    )
    assert overcommits.resolve(match) == []


def test_a_loose_ball_is_no_opponent_possession() -> None:
    match = played(
        {0: between(1.5, 3.0, 600.0, -800.0), 1: between(1.5, 3.0, 400.0, -2000.0)} | ORANGE_HOME,
        [touch(1.0, 2)],
    )
    assert overcommits.resolve(match) == []


def test_a_demolished_teammate_is_not_ahead() -> None:
    match = played(
        {0: between(1.5, 3.0, 600.0, -800.0), 1: between(1.5, 3.0, 400.0, -2000.0)} | ORANGE_HOME,
        demolished=lambda player, index: player == 1 and index * DT >= 2.0,
    )
    assert overcommits.resolve(match) == []


def test_orange_is_read_the_same_way_mirrored() -> None:
    match = played(
        {
            0: at(-1000.0),
            1: at(-2000.0),
            2: between(1.5, 3.0, -600.0, 800.0),
            3: between(1.5, 3.0, -400.0, 2000.0),
        },
        BLUE_HOLDS,
    )
    [found] = overcommits.resolve(match) or []
    assert (found.team, found.players) == (1, (2, 3))
    assert overcommits.count(match) == {0: 0.0, 1: 1.0}


def test_a_1v1_has_no_overcommit_and_no_touches_nothing() -> None:
    duel = played({0: at(600.0), 2: at(1000.0)}, teams={0: 0, 2: 1})
    assert overcommits.count(duel) == {0: None, 1: None}
    unknown = played({0: at(0.0), 1: at(0.0)} | ORANGE_HOME, None)
    assert overcommits.resolve(unknown) is None
    assert overcommits.count(unknown) == {0: None, 1: None}
