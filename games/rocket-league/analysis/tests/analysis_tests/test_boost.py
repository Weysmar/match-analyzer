"""Boost metrics, on frames and events made by hand."""

import pytest

from rl_analysis import boost
from rl_analysis.constants import BOOST_FULL_MIN, BOOST_ZERO_MAX, Phase

from .synthetic import frames, match_of, pickup, row


def test_the_average_counts_kickoff_waiting_and_live_play_only() -> None:
    """60 for 2 s waiting for the kickoff, 30 for 2 s of play: 45. The countdown and the time after
    a goal, at 100, do not count."""
    frame = frames(
        row(phase=int(Phase.COUNTDOWN), boost=100.0, dt_s=5.0),
        row(phase=int(Phase.KICKOFF_WAITING), boost=60.0, dt_s=2.0),
        row(phase=int(Phase.ACTIVE), boost=30.0, dt_s=2.0),
        row(phase=int(Phase.AFTER_GOAL), boost=100.0, dt_s=5.0),
    )
    assert boost.average(match_of(frame)) == {0: pytest.approx(45.0)}


def test_a_demolished_car_does_not_count() -> None:
    frame = frames(row(boost=20.0, dt_s=1.0), row(boost=100.0, dt_s=3.0, demolished=True))
    assert boost.average(match_of(frame)) == {0: pytest.approx(20.0)}


def test_an_empty_tank_is_one_raw_unit_at_most() -> None:
    """Raw 0 and 1 are empty, raw 2 is not: 1 s empty out of 4."""
    frame = frames(
        row(boost=0.0, dt_s=0.5),
        row(boost=BOOST_ZERO_MAX, dt_s=0.5),
        row(boost=100.0 * 2 / 255, dt_s=1.0),
        row(boost=50.0, dt_s=2.0),
    )
    assert boost.time_empty(match_of(frame)) == {0: pytest.approx(25.0)}


def test_a_full_tank_is_one_raw_unit_from_the_top() -> None:
    """Raw 255 and 254 are full, raw 253 is not: 2 s full out of 5."""
    frame = frames(
        row(boost=100.0, dt_s=1.0),
        row(boost=BOOST_FULL_MIN, dt_s=1.0),
        row(boost=100.0 * 253 / 255, dt_s=1.0),
        row(boost=10.0, dt_s=2.0),
    )
    assert boost.time_full(match_of(frame)) == {0: pytest.approx(40.0)}


def test_an_unknown_boost_is_left_out_of_every_metric() -> None:
    frame = frames(row(boost=0.0, dt_s=1.0), row(boost=None, dt_s=9.0))
    match = match_of(frame)
    assert boost.average(match) == {0: pytest.approx(0.0)}
    assert boost.time_empty(match) == {0: pytest.approx(100.0)}
    assert boost.time_full(match) == {0: pytest.approx(0.0)}


def test_teams_are_measured_alike() -> None:
    frame = frames(
        row(player_idx=0, team=0, boost=0.0, y=-3000.0),
        row(player_idx=1, team=1, boost=0.0, y=3000.0),
    )
    assert boost.time_empty(match_of(frame)) == {0: pytest.approx(100.0), 1: pytest.approx(100.0)}


def test_a_player_with_a_few_frames_only() -> None:
    """The spike's worst cases were players with under 5 s of presence: the result stays defined."""
    frame = frames(
        row(player_idx=0, boost=33.0, dt_s=0.03),
        row(player_idx=1, team=1, boost=80.0, dt_s=300.0),
    )
    assert boost.average(match_of(frame)) == {0: pytest.approx(33.0), 1: pytest.approx(80.0)}


def test_a_player_never_in_play_has_no_values() -> None:
    match = match_of(frames(row(present=False, boost=None)))
    assert boost.average(match) == {0: None}
    assert boost.time_empty(match) == {0: None}
    assert boost.time_full(match) == {0: None}
    assert boost.used_per_minute(match) == {0: None}


def test_consumption_is_the_sum_of_the_falls() -> None:
    """100, 80, 90 (a pad), 60: 20 and 30 used, 50 in 4 s, so 750 per minute."""
    frame = frames(*(row(boost=value, dt_s=1.0) for value in (100.0, 80.0, 90.0, 60.0)))
    assert boost.used_per_minute(match_of(frame)) == {0: pytest.approx(750.0)}


def test_the_kickoff_reset_is_not_boost_used() -> None:
    """From 100 to 33 during the countdown, then 33 to 23 in play: only 10 is used, in 2 s."""
    frame = frames(
        row(boost=100.0, dt_s=1.0, phase=int(Phase.AFTER_GOAL)),
        row(boost=33.3, dt_s=1.0, phase=int(Phase.COUNTDOWN)),
        row(boost=33.3, dt_s=1.0, phase=int(Phase.KICKOFF_WAITING)),
        row(boost=23.3, dt_s=1.0, phase=int(Phase.ACTIVE)),
    )
    assert boost.used_per_minute(match_of(frame)) == {0: pytest.approx(300.0)}


def test_a_fall_while_demolished_is_not_counted() -> None:
    frame = frames(
        row(boost=80.0, dt_s=1.0),
        row(boost=0.0, dt_s=1.0, demolished=True),
        row(boost=33.3, dt_s=1.0),
        row(boost=23.3, dt_s=1.0),
    )
    # 10 used in the 3 s of reference time.
    assert boost.used_per_minute(match_of(frame)) == {0: pytest.approx(200.0)}


def test_a_gap_in_the_boost_falls_back_on_the_last_known_value() -> None:
    frame = frames(row(boost=60.0), row(boost=None), row(boost=50.0))
    # 10 used over the 2 s with a known boost.
    assert boost.used_per_minute(match_of(frame)) == {0: pytest.approx(300.0)}


def test_players_do_not_mix_their_boost() -> None:
    """Frames of two players interleaved: each one's previous value is their own."""
    frame = frames(
        row(player_idx=0, boost=100.0),
        row(player_idx=1, team=1, boost=0.0),
        row(player_idx=0, boost=90.0),
        row(player_idx=1, team=1, boost=0.0),
    )
    assert boost.used_per_minute(match_of(frame)) == {0: pytest.approx(300.0), 1: 0.0}


def test_pads_by_size_and_half() -> None:
    frame = frames(row(player_idx=0, team=0), row(player_idx=1, team=1))
    match = match_of(
        frame,
        pad_pickups=[
            pickup(0, "big", 3000.0),
            pickup(0, "small", -1000.0),
            pickup(0, "small", 500.0),
            pickup(1, "big", 3000.0),
            pickup(1, "big", -3000.0),
        ],
    )
    assert boost.pads_big(match) == {0: 1.0, 1: 2.0}
    assert boost.pads_small(match) == {0: 2.0, 1: 0.0}
    # Orange attacks towards y < 0: its pad at y = -3000 is in the opponents' half.
    assert boost.pads_enemy_half(match) == {0: 2.0, 1: 1.0}


def test_a_player_who_switches_teams_attacks_the_other_half_afterwards() -> None:
    """Blue on frame 0, orange from frame 1 on: the same pad at y = -3000 is in the opponents'
    half only once orange."""
    frame = frames(row(frame=0, team=0), row(frame=1, team=1))
    first = pickup(0, "big", -3000.0) | {"frame": 0}
    later = pickup(0, "big", -3000.0) | {"frame": 1}
    match = match_of(frame.filter(frame["frame"] == 0), pad_pickups=[first, later])
    switched = type(match)(frame, match.events)
    assert boost.pads_enemy_half(switched) == {0: 1.0}


def test_a_pad_on_the_halfway_line_is_not_in_the_opponents_half() -> None:
    match = match_of(frames(row()), pad_pickups=[pickup(0, "small", 0.0)])
    assert boost.pads_enemy_half(match) == {0: 0.0}


@pytest.mark.parametrize(
    ("phase", "counted"),
    [
        (Phase.COUNTDOWN, 0.0),
        (Phase.KICKOFF_WAITING, 1.0),
        (Phase.ACTIVE, 1.0),
        (Phase.AFTER_GOAL, 0.0),
    ],
)
def test_pads_count_on_reference_time_only(phase: Phase, counted: float) -> None:
    match = match_of(frames(row()), pad_pickups=[pickup(0, "big", 0.0, phase=phase)])
    assert boost.pads_big(match) == {0: counted}


def test_a_player_without_pads_has_none_counted() -> None:
    match = match_of(
        frames(row(player_idx=0), row(player_idx=1, team=1)),
        pad_pickups=[pickup(1, "small", 0.0)],
    )
    assert boost.pads_big(match) == {0: 0.0, 1: 0.0}
    assert boost.pads_small(match) == {0: 0.0, 1: 1.0}


def test_a_replay_without_any_pickup_says_nothing_about_pads() -> None:
    """Some old replays do not replicate pickups: 0 would be false, so the count is unknown."""
    match = match_of(frames(row(player_idx=0), row(player_idx=1, team=1)))
    assert boost.pads_big(match) == {0: None, 1: None}
    assert boost.pads_small(match) == {0: None, 1: None}
    assert boost.pads_enemy_half(match) == {0: None, 1: None}
