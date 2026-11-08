"""The game clock (A63), on frames made by hand: one second per frame unless said otherwise."""

from typing import Any

import pytest

from rl_analysis import clock
from rl_analysis.constants import Phase

from .synthetic import frames, match_of, row


def phases(*runs: tuple[Phase, int]) -> list[dict[str, Any]]:
    """Consecutive frames of one player, `count` frames in each phase."""
    rows = []
    for phase, count in runs:
        rows += [row(phase=int(phase)) for _ in range(count)]
    for index, given in enumerate(rows):
        given["frame"] = index
        given["time_s"] = float(index)
    return rows


def goal(frame: int, team: int = 0) -> dict[str, Any]:
    return {
        "frame": frame,
        "time_s": float(frame),
        "team": team,
        "player_idx": 0,
        "score_blue": None,
        "score_orange": None,
    }


def regulation_then(*after: tuple[Phase, int]) -> list[dict[str, Any]]:
    """A kickoff, then 302 s of play, as the corpus measures a five-minute match."""
    return phases((Phase.COUNTDOWN, 3), (Phase.KICKOFF_WAITING, 2), (Phase.ACTIVE, 302), *after)


def test_the_clock_counts_active_play_only() -> None:
    rows = phases(
        (Phase.COUNTDOWN, 3),
        (Phase.KICKOFF_WAITING, 2),
        (Phase.ACTIVE, 10),
        (Phase.AFTER_GOAL, 5),
        (Phase.COUNTDOWN, 3),
        (Phase.ACTIVE, 4),
    )
    result = clock.compute(match_of(frames(*rows), goals=[goal(14)]))
    assert result.length_s == pytest.approx(14.0)
    # Frame 14 is the tenth active frame: the goal comes at 10 s, whatever the replay's time.
    assert result.goals_s == [pytest.approx(10.0)]
    assert result.overtime_from_s is None


def test_frames_are_counted_once_whatever_the_number_of_players() -> None:
    rows = phases((Phase.ACTIVE, 10))
    both = rows + [given | {"player_idx": 1, "team": 1} for given in rows]
    assert clock.compute(match_of(frames(*both))).length_s == pytest.approx(10.0)


def test_uneven_frames_count_by_their_duration() -> None:
    rows = phases((Phase.ACTIVE, 4))
    for given, dt in zip(rows, (0.5, 0.25, 1.0, 2.0), strict=True):
        given["dt_s"] = dt
    assert clock.compute(match_of(frames(*rows))).length_s == pytest.approx(3.75)


def test_overtime_starts_with_a_countdown_straight_after_play() -> None:
    rows = regulation_then((Phase.COUNTDOWN, 3), (Phase.ACTIVE, 40), (Phase.AFTER_GOAL, 3))
    golden = len(rows) - 4
    result = clock.compute(match_of(frames(*rows), goals=[goal(golden)]))
    assert result.overtime_from_s == pytest.approx(302.0)
    assert result.goals_s[0] == pytest.approx(342.0)
    assert result.length_s == pytest.approx(342.0)


def test_a_goal_at_the_end_of_regulation_is_no_overtime() -> None:
    rows = regulation_then((Phase.AFTER_GOAL, 5))
    assert clock.compute(match_of(frames(*rows))).overtime_from_s is None


def test_a_kickoff_after_a_goal_late_in_the_match_is_no_overtime() -> None:
    rows = phases(
        (Phase.ACTIVE, 298), (Phase.AFTER_GOAL, 5), (Phase.COUNTDOWN, 3), (Phase.ACTIVE, 4)
    )
    assert clock.compute(match_of(frames(*rows))).overtime_from_s is None


def test_unknown_frames_between_play_and_countdown_change_nothing() -> None:
    rows = regulation_then((Phase.UNKNOWN, 2), (Phase.COUNTDOWN, 3), (Phase.ACTIVE, 5))
    assert clock.compute(match_of(frames(*rows))).overtime_from_s == pytest.approx(302.0)


def test_a_sliver_of_play_before_the_first_countdown_is_no_overtime() -> None:
    rows = phases((Phase.ACTIVE, 1), (Phase.COUNTDOWN, 3), (Phase.ACTIVE, 400))
    rows[0]["dt_s"] = 0.0
    assert clock.compute(match_of(frames(*rows))).overtime_from_s is None


@pytest.mark.parametrize("played", [108, 600])
def test_a_reset_far_from_the_end_of_regulation_is_no_overtime(played: int) -> None:
    """Measured on the corpus: a kickoff reset at 108 s in a private match, a 38-minute match."""
    rows = phases((Phase.ACTIVE, played), (Phase.COUNTDOWN, 3), (Phase.ACTIVE, 20))
    assert clock.compute(match_of(frames(*rows))).overtime_from_s is None


def test_a_match_without_frames_has_no_clock() -> None:
    empty = frames().head(0)
    result = clock.compute(match_of(empty, goals=[goal(3)]))
    assert result == clock.Clock(None, None, [None])
