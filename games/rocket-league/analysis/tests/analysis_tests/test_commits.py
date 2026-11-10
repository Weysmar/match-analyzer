"""The engaged player (T14.2) and double commits (T14.3), on frames made by hand. Frames every
0.05 s; the ball waits at the center unless a test moves it."""

from collections.abc import Callable
from typing import Any

import pytest

from rl_analysis import commits, engagement
from rl_analysis.constants import Phase

from .synthetic import frames, match_of, row

DT = 0.05
# Players 0 and 1 for blue, 2 and 3 for orange.
TEAM = {0: 0, 1: 0, 2: 1, 3: 1}
# A car: its fields at a frame index.
Car = Callable[[int], dict[str, Any]]


def mover(start_x: float, speed: float, *, dodge_from: int | None = None) -> Car:
    """A car on the x axis, from `start_x` towards the ball at the center (negative speed: away)."""
    toward = -1.0 if start_x > 0 else 1.0

    def at(index: int) -> dict[str, Any]:
        return {
            "x": start_x + toward * speed * index * DT,
            "vx": toward * speed,
            "dodged": dodge_from is not None and index >= dodge_from,
        }

    return at


def still(x: float) -> Car:
    return lambda _index: {"x": x, "vx": 0.0, "dodged": False}


def played(
    cars: dict[int, Any], count: int = 40, *, phase: Any = lambda _i: Phase.ACTIVE, **events: Any
) -> Any:
    rows = []
    for index in range(count):
        for player, team in TEAM.items():
            rows.append(
                row(
                    frame=index,
                    time_s=index * DT,
                    dt_s=0.0 if index == 0 else DT,
                    phase=int(phase(index)),
                    player_idx=player,
                    team=team,
                    **cars[player](index),
                )
            )
    return match_of(frames(*rows), **({"touches": []} | events))


def touch(time_s: float, player: int) -> dict[str, Any]:
    return {
        "frame": round(time_s / DT),
        "time_s": time_s,
        "player_idx": player,
        "team": TEAM[player],
        "ball_speed_change": 800.0,
        "kind": None,
        "height_band": None,
        "surface": None,
        "contested": False,
    }


def engaged_from(match: Any, player: int) -> float | None:
    """The first time the player is engaged, or None."""
    return next((t for t, e in engagement.resolve(match)[player] if e), None)


AWAY = {2: still(-3000.0), 3: still(-3500.0)}


def test_a_fast_approach_is_engaged_once_it_has_lasted() -> None:
    match = played({0: mover(1200.0, 1000.0), 1: still(4000.0)} | AWAY)
    first = engaged_from(match, 0)
    # Distance down 200 uu and 0.4 s of history: from 0.4 s on, with the car about 700 uu away.
    assert first == pytest.approx(0.4)
    assert engaged_from(match, 1) is None


def test_a_player_driving_away_is_not_engaged() -> None:
    match = played({0: mover(300.0, -1000.0), 1: still(4000.0)} | AWAY)
    assert engaged_from(match, 0) is None


def test_a_slow_approach_needs_a_dodge() -> None:
    slow = played({0: mover(1000.0, 300.0), 1: still(4000.0)} | AWAY)
    assert engaged_from(slow, 0) is None
    dodging = played({0: mover(1000.0, 300.0, dodge_from=10), 1: still(4000.0)} | AWAY)
    assert engaged_from(dodging, 0) is not None


def test_too_far_from_the_ball_is_not_engaged() -> None:
    match = played({0: mover(4000.0, 1000.0), 1: still(4500.0)} | AWAY, count=20)
    assert engaged_from(match, 0) is None


def test_a_demolished_car_starts_afresh() -> None:
    # Demolished from frame 6 to 9: the history restarts at frame 10.
    demolished = match_of(
        frames(
            *[
                row(
                    frame=index,
                    time_s=index * DT,
                    dt_s=0.0 if index == 0 else DT,
                    player_idx=0,
                    team=0,
                    demolished=6 <= index < 10,
                    **mover(1200.0, 1000.0)(index),
                )
                for index in range(30)
            ]
        )
    )
    first = engaged_from(demolished, 0)
    assert first is not None
    assert first >= 10 * DT + 0.4 - 1e-9


def test_two_teammates_going_together_with_a_touch_are_a_double_commit() -> None:
    match = played(
        {0: mover(1200.0, 1000.0), 1: mover(1250.0, 1000.0)} | AWAY,
        touches=[touch(1.0, 0)],
    )
    [commit] = commits.resolve(match) or []
    assert (commit.team, commit.players) == (0, (0, 1))
    assert commit.time_s == pytest.approx(0.4)
    assert commit.touch_s == 1.0
    assert commits.count(match) == {0: 1.0, 1: 1.0, 2: 0.0, 3: 0.0}


def test_one_player_engaged_is_no_double_commit() -> None:
    match = played({0: mover(1200.0, 1000.0), 1: still(4000.0)} | AWAY, touches=[touch(1.0, 0)])
    assert commits.resolve(match) == []


def test_without_a_touch_soon_enough_it_is_no_double_commit() -> None:
    match = played(
        {0: mover(1200.0, 1000.0), 1: mover(1250.0, 1000.0)} | AWAY,
        count=60,
        touches=[touch(2.5, 0)],
    )
    assert commits.resolve(match) == []


def test_the_kickoff_scramble_is_left_out() -> None:
    """Countdown, then the cars free from 0.3 s, the first touch at 1.0 s: until 3.0 s, a choice."""

    def phase(i: int) -> Phase:
        return Phase.COUNTDOWN if i < 6 else Phase.KICKOFF_WAITING if i < 20 else Phase.ACTIVE

    match = played(
        {0: mover(1200.0, 1000.0), 1: mover(1250.0, 1000.0)} | AWAY,
        phase=phase,
        touches=[touch(1.0, 0)],
    )
    assert commits.resolve(match) == []


@pytest.mark.parametrize(
    ("start", "end", "touches", "expected"),
    [
        (10.0, 10.2, [10.5], False),  # together 0.2 s only
        (10.0, 10.3, [10.5], True),
        (10.0, 10.3, [11.6], False),  # the touch comes after 1.5 s
        (10.0, 10.3, [9.0], False),  # no touch after the start
    ],
)
def test_a_double_commit_needs_its_overlap_and_its_touch(
    start: float, end: float, touches: list[float], expected: bool
) -> None:
    found = commits._confirmed(start, end, 0, {0, 1}, touches, [], [])
    assert (found is not None) is expected


@pytest.mark.parametrize(
    ("threat", "punished"),
    [((14.0, 1), True), ((16.0, 1), False), ((14.0, 0), False), ((10.2, 1), False)],
)
def test_punished_when_the_opponents_shoot_or_score_within_5_s(
    threat: tuple[float, int], punished: bool
) -> None:
    found = commits._confirmed(10.0, 10.3, 0, {0, 1}, [10.5], [], [threat])
    assert found is not None
    assert found.punished is punished


def test_a_1v1_has_no_double_commits() -> None:
    duel = match_of(frames(row(player_idx=0, team=0), row(player_idx=1, team=1)), touches=[])
    assert commits.count(duel) == {0: None, 1: None}


def test_without_touches_nothing_is_known() -> None:
    match = played({0: still(1000.0), 1: still(2000.0)} | AWAY, touches=None)
    assert commits.resolve(match) is None
    assert commits.count(match) == dict.fromkeys(TEAM)


def test_a_double_commit_is_a_situation_with_its_punishment() -> None:
    from rl_analysis import situations

    match = played(
        {0: mover(1200.0, 1000.0), 1: mover(1250.0, 1000.0)} | AWAY,
        touches=[touch(1.0, 0)],
        stat_events=[{"frame": 30, "time_s": 1.5, "player_idx": 2, "kind": "shot"}],
    )
    [found] = [s for s in situations.detect(match) or [] if s.kind == "double_commit"]
    assert (found.team, found.players, found.details) == (0, (0, 1), {"punished": True})
