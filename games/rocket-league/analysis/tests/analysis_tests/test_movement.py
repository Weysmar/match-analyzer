"""Movement metrics, on frames made by hand."""

import math

import pytest

from rl_analysis import movement
from rl_analysis.constants import GROUND_MAX_Z, HIGH_AIR_MIN_Z, Phase

from .synthetic import frames, match_of, row


def test_speed_is_the_length_of_the_velocity() -> None:
    """3-4-12 gives 13, for 1 s; 1000 along x for 3 s: (13 + 3000) / 4."""
    frame = frames(row(vx=3.0, vy=4.0, vz=12.0, dt_s=1.0), row(vx=1000.0, dt_s=3.0))
    assert movement.speed_average(match_of(frame)) == {0: pytest.approx(3013.0 / 4)}


def test_a_frame_without_velocity_is_left_out() -> None:
    frame = frames(row(vx=500.0, dt_s=1.0), row(vx=None, vy=None, vz=None, dt_s=9.0))
    assert movement.speed_average(match_of(frame)) == {0: pytest.approx(500.0)}
    assert movement.time_supersonic(match_of(frame)) == {0: pytest.approx(0.0)}


def test_speed_counts_on_reference_time_only() -> None:
    frame = frames(
        row(vx=2000.0, phase=int(Phase.COUNTDOWN)),
        row(vx=1000.0, phase=int(Phase.KICKOFF_WAITING)),
        row(vx=1500.0, demolished=True),
        row(vx=600.0, phase=int(Phase.AFTER_GOAL)),
    )
    assert movement.speed_average(match_of(frame)) == {0: pytest.approx(1000.0)}


def test_supersonic_starts_at_2200() -> None:
    frame = frames(row(vx=2199.0), row(vx=2200.0), row(vx=2300.0), row(vx=0.0))
    assert movement.time_supersonic(match_of(frame)) == {0: pytest.approx(50.0)}


def test_supersonic_counts_every_direction() -> None:
    component = 2300.0 / math.sqrt(3)
    frame = frames(row(vx=-component, vy=component, vz=-component))
    assert movement.time_supersonic(match_of(frame)) == {0: pytest.approx(100.0)}


def test_altitude_bands_and_their_edges() -> None:
    """17 and 20 on the ground, 21 and just under 735.5 in low air, 735.5 and above in high air."""
    frame = frames(
        row(z=17.0),
        row(z=GROUND_MAX_Z),
        row(z=21.0),
        row(z=HIGH_AIR_MIN_Z - 0.1),
        row(z=HIGH_AIR_MIN_Z),
        row(z=1800.0),
    )
    match = match_of(frame)
    assert movement.time_on_ground(match) == {0: pytest.approx(100 / 3)}
    assert movement.time_in_low_air(match) == {0: pytest.approx(100 / 3)}
    assert movement.time_in_high_air(match) == {0: pytest.approx(100 / 3)}


def test_the_bands_add_up_to_the_whole_time() -> None:
    frame = frames(
        *(row(z=z, dt_s=dt) for z, dt in [(17.0, 0.4), (300.0, 1.3), (900.0, 0.03), (50.0, 2.0)])
    )
    match = match_of(frame)
    total = sum(
        band(match)[0] or 0.0
        for band in (movement.time_on_ground, movement.time_in_low_air, movement.time_in_high_air)
    )
    assert total == pytest.approx(100.0)


def test_orange_and_blue_are_measured_alike() -> None:
    frame = frames(
        row(player_idx=0, team=0, vx=1000.0, z=17.0),
        row(player_idx=1, team=1, vx=-1000.0, z=17.0),
    )
    match = match_of(frame)
    assert movement.speed_average(match) == {0: pytest.approx(1000.0), 1: pytest.approx(1000.0)}
    assert movement.time_on_ground(match) == {0: pytest.approx(100.0), 1: pytest.approx(100.0)}


def test_a_player_never_in_play_has_no_values() -> None:
    match = match_of(frames(row(present=False, z=None, vx=None, vy=None, vz=None)))
    assert movement.speed_average(match) == {0: None}
    assert movement.time_on_ground(match) == {0: None}
