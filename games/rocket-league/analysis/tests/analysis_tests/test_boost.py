"""Boost metrics, on frames made by hand."""

import pytest

from rl_analysis import boost
from rl_analysis.constants import BOOST_FULL_MIN, BOOST_ZERO_MAX, Phase

from .synthetic import frames, row


def test_the_average_counts_kickoff_waiting_and_live_play_only() -> None:
    """60 for 2 s waiting for the kickoff, 30 for 2 s of play: 45. The countdown and the time after
    a goal, at 100, do not count."""
    frame = frames(
        row(phase=int(Phase.COUNTDOWN), boost=100.0, dt_s=5.0),
        row(phase=int(Phase.KICKOFF_WAITING), boost=60.0, dt_s=2.0),
        row(phase=int(Phase.ACTIVE), boost=30.0, dt_s=2.0),
        row(phase=int(Phase.AFTER_GOAL), boost=100.0, dt_s=5.0),
    )
    assert boost.average(frame) == {0: pytest.approx(45.0)}


def test_a_demolished_car_does_not_count() -> None:
    frame = frames(row(boost=20.0, dt_s=1.0), row(boost=100.0, dt_s=3.0, demolished=True))
    assert boost.average(frame) == {0: pytest.approx(20.0)}


def test_an_empty_tank_is_one_raw_unit_at_most() -> None:
    """Raw 0 and 1 are empty, raw 2 is not: 1 s empty out of 4."""
    frame = frames(
        row(boost=0.0, dt_s=0.5),
        row(boost=BOOST_ZERO_MAX, dt_s=0.5),
        row(boost=100.0 * 2 / 255, dt_s=1.0),
        row(boost=50.0, dt_s=2.0),
    )
    assert boost.time_empty(frame) == {0: pytest.approx(25.0)}


def test_a_full_tank_is_one_raw_unit_from_the_top() -> None:
    """Raw 255 and 254 are full, raw 253 is not: 2 s full out of 5."""
    frame = frames(
        row(boost=100.0, dt_s=1.0),
        row(boost=BOOST_FULL_MIN, dt_s=1.0),
        row(boost=100.0 * 253 / 255, dt_s=1.0),
        row(boost=10.0, dt_s=2.0),
    )
    assert boost.time_full(frame) == {0: pytest.approx(40.0)}


def test_an_unknown_boost_is_left_out_of_every_metric() -> None:
    frame = frames(row(boost=0.0, dt_s=1.0), row(boost=None, dt_s=9.0))
    assert boost.average(frame) == {0: pytest.approx(0.0)}
    assert boost.time_empty(frame) == {0: pytest.approx(100.0)}
    assert boost.time_full(frame) == {0: pytest.approx(0.0)}


def test_teams_are_measured_alike() -> None:
    frame = frames(
        row(player_idx=0, team=0, boost=0.0, y=-3000.0),
        row(player_idx=1, team=1, boost=0.0, y=3000.0),
    )
    assert boost.time_empty(frame) == {0: pytest.approx(100.0), 1: pytest.approx(100.0)}


def test_a_player_with_a_few_frames_only() -> None:
    """The spike's worst cases were players with under 5 s of presence: the result stays defined."""
    frame = frames(
        row(player_idx=0, boost=33.0, dt_s=0.03),
        row(player_idx=1, team=1, boost=80.0, dt_s=300.0),
    )
    assert boost.average(frame) == {0: pytest.approx(33.0), 1: pytest.approx(80.0)}


def test_a_player_never_in_play_has_no_values() -> None:
    frame = frames(row(present=False, boost=None))
    assert boost.average(frame) == {0: None}
    assert boost.time_empty(frame) == {0: None}
    assert boost.time_full(frame) == {0: None}
