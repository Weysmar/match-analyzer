"""Rotation roles (T14.1), on frames made by hand: the ball at the center, players placed along x.
Frames every 0.05 s, so the 0.35 s debounce is 7 frames."""

from collections.abc import Callable
from typing import Any

import pytest

from rl_analysis import rotation
from rl_analysis.constants import Phase
from rl_analysis.rotation import Role

from .synthetic import frames, match_of, row

DT = 0.05

# Where a player stands at a frame index: its distance to the ball along x.
Placement = Callable[[int], float]


def played(
    teams: dict[int, int],
    placements: dict[int, Placement],
    count: int = 100,
    *,
    phase: Callable[[int], Phase] = lambda _: Phase.ACTIVE,
    demolished: Callable[[int, int], bool] = lambda _p, _i: False,
) -> Any:
    rows = []
    for index in range(count):
        for player, team in teams.items():
            rows.append(
                row(
                    frame=index,
                    time_s=index * DT,
                    dt_s=0.0 if index == 0 else DT,
                    phase=int(phase(index)),
                    player_idx=player,
                    team=team,
                    x=placements[player](index),
                    demolished=demolished(player, index),
                )
            )
    return match_of(frames(*rows))


def at(distance: float) -> Placement:
    return lambda _: distance


TWOS = {0: 0, 1: 0, 2: 1, 3: 1}


def test_the_closest_by_more_than_250_uu_is_first_man() -> None:
    match = played(TWOS, {0: at(500), 1: at(1000), 2: at(-600), 3: at(-1200)})
    assert rotation.first_share(match) == {0: 100.0, 1: 0.0, 2: 100.0, 3: 0.0}
    assert rotation.second_share(match) == {0: 0.0, 1: 100.0, 2: 0.0, 3: 100.0}


def test_too_close_a_call_is_ambiguous_and_stays_out() -> None:
    # Blue's two players 200 uu apart from the ball: nobody's role is known.
    match = played(TWOS, {0: at(500), 1: at(700), 2: at(-600), 3: at(-1200)})
    assert rotation.first_share(match)[0] is None
    seconds = rotation.resolve(match).seconds[0]
    assert seconds[Role.AMBIGUOUS] == pytest.approx(99 * DT)


def test_a_swap_shorter_than_the_debounce_changes_nothing() -> None:
    # Player 1 is closest for 5 frames (0.25 s) only, from frame 50.
    swap = lambda index: 300.0 if 50 <= index < 55 else 1000.0  # noqa: E731
    match = played(TWOS, {0: at(600), 1: swap, 2: at(-600), 3: at(-1200)})
    assert rotation.first_share(match)[1] == 0.0


def test_a_lasting_swap_takes_effect_after_the_debounce() -> None:
    # Player 1 is closest from frame 50 to the end: first man from frame 56 (7 frames later).
    swap = lambda index: 300.0 if index >= 50 else 1000.0  # noqa: E731
    match = played(TWOS, {0: at(600), 1: swap, 2: at(-600), 3: at(-1200)})
    seconds = rotation.resolve(match).seconds
    assert seconds[1][Role.FIRST] == pytest.approx((100 - 56) * DT)
    assert seconds[0][Role.FIRST] == pytest.approx((56 - 1) * DT)


def test_shares_add_up_to_100() -> None:
    swap = lambda index: 300.0 if index >= 50 else 1000.0  # noqa: E731
    match = played(TWOS, {0: at(600), 1: swap, 2: at(-600), 3: at(-1200)})
    for player in TWOS:
        total = (rotation.first_share(match)[player] or 0) + (
            rotation.second_share(match)[player] or 0
        )
        assert total == pytest.approx(100.0)


def test_a_demolished_teammate_leaves_the_team_without_roles() -> None:
    match = played(
        TWOS,
        {0: at(500), 1: at(1000), 2: at(-600), 3: at(-1200)},
        demolished=lambda player, index: player == 1 and index >= 50,
    )
    seconds = rotation.resolve(match).seconds
    assert seconds[0][Role.FIRST] == pytest.approx(49 * DT)
    # Orange is whole all along.
    assert seconds[2][Role.FIRST] == pytest.approx(99 * DT)


def test_only_live_play_counts() -> None:
    match = played(
        TWOS,
        {0: at(500), 1: at(1000), 2: at(-600), 3: at(-1200)},
        phase=lambda index: Phase.COUNTDOWN if index < 50 else Phase.ACTIVE,
    )
    assert rotation.resolve(match).seconds[0][Role.FIRST] == pytest.approx(50 * DT)


def test_a_1v1_has_no_roles_and_a_2v2_no_third_man() -> None:
    duel = played({0: 0, 1: 1}, {0: at(500), 1: at(-600)})
    assert rotation.first_share(duel) == {0: None, 1: None}
    twos = played(TWOS, {0: at(500), 1: at(1000), 2: at(-600), 3: at(-1200)})
    assert rotation.third_share(twos) == dict.fromkeys(TWOS)


def test_a_3v3_has_a_third_man() -> None:
    threes = {0: 0, 1: 0, 2: 0, 3: 1, 4: 1, 5: 1}
    match = played(
        threes, {0: at(500), 1: at(1000), 2: at(1600), 3: at(-500), 4: at(-1000), 5: at(-1600)}
    )
    assert rotation.third_share(match)[2] == 100.0
    assert rotation.second_share(match)[1] == 100.0
    assert rotation.first_share(match)[3] == 100.0
