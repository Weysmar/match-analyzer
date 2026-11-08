"""Positioning and demolitions, on frames and events made by hand."""

import math
from typing import Any

import pytest

from rl_analysis import positioning
from rl_analysis.constants import THIRD_Y, Phase

from .synthetic import frames, match_of, row


def demolition(attacker: int | None, victim: int | None) -> dict[str, Any]:
    return {
        "frame": 0,
        "time_s": 0.0,
        "attacker_idx": attacker,
        "victim_idx": victim,
        "x": 0.0,
        "y": 0.0,
        "z": 17.0,
    }


def test_thirds_of_the_field() -> None:
    """One second in each third, with the edges in the middle one."""
    frame = frames(
        row(y=-4000.0),
        row(y=-THIRD_Y),
        row(y=0.0),
        row(y=THIRD_Y),
        row(y=4000.0),
        row(y=-5900.0),
    )
    match = match_of(frame)
    assert positioning.defensive_third(match) == {0: pytest.approx(200 / 6)}
    assert positioning.middle_third(match) == {0: pytest.approx(300 / 6)}
    assert positioning.attacking_third(match) == {0: pytest.approx(100 / 6)}


def test_orange_defends_the_other_side() -> None:
    frame = frames(
        row(player_idx=0, team=0, y=-4000.0),
        row(player_idx=1, team=1, y=-4000.0),
    )
    match = match_of(frame)
    assert positioning.defensive_third(match) == {0: pytest.approx(100.0), 1: pytest.approx(0.0)}
    assert positioning.attacking_third(match) == {0: pytest.approx(0.0), 1: pytest.approx(100.0)}


def test_the_thirds_add_up_to_the_whole_time() -> None:
    frame = frames(*(row(y=y, dt_s=dt) for y, dt in [(-3000.0, 0.3), (100.0, 1.7), (2500.0, 0.05)]))
    match = match_of(frame)
    total = sum(
        share(match)[0] or 0.0
        for share in (
            positioning.defensive_third,
            positioning.middle_third,
            positioning.attacking_third,
        )
    )
    assert total == pytest.approx(100.0)


def test_positioning_counts_live_play_only() -> None:
    """Kickoff waiting counts for boost and movement, not for positioning."""
    frame = frames(
        row(y=-4000.0, phase=int(Phase.KICKOFF_WAITING)),
        row(y=4000.0, phase=int(Phase.ACTIVE)),
        row(y=-4000.0, demolished=True),
    )
    assert positioning.attacking_third(match_of(frame)) == {0: pytest.approx(100.0)}


def test_ahead_and_behind_the_ball() -> None:
    frame = frames(
        row(y=1000.0, ball_y=0.0),
        row(y=-1000.0, ball_y=0.0),
        row(y=-500.0, ball_y=0.0),
        row(y=0.0, ball_y=0.0),
    )
    match = match_of(frame)
    assert positioning.ahead_of_ball(match) == {0: pytest.approx(25.0)}
    assert positioning.behind_ball(match) == {0: pytest.approx(50.0)}


def test_ahead_is_towards_the_goal_the_team_attacks() -> None:
    frame = frames(
        row(player_idx=0, team=0, y=1000.0, ball_y=0.0),
        row(player_idx=1, team=1, y=1000.0, ball_y=0.0),
    )
    match = match_of(frame)
    assert positioning.ahead_of_ball(match) == {0: pytest.approx(100.0), 1: pytest.approx(0.0)}
    assert positioning.behind_ball(match) == {0: pytest.approx(0.0), 1: pytest.approx(100.0)}


def test_a_margin_leaves_the_frames_near_the_ball_out() -> None:
    """What subtr-actor does, with 150 uu: 100 ahead counts for neither side."""
    frame = frames(row(y=100.0, ball_y=0.0), row(y=500.0, ball_y=0.0))
    ahead, behind = positioning.ahead_and_behind(match_of(frame), margin=150.0)
    assert ahead == {0: pytest.approx(50.0)}
    assert behind == {0: pytest.approx(0.0)}


def test_a_frame_without_a_ball_is_left_out() -> None:
    frame = frames(
        row(y=1000.0, ball_y=0.0, dt_s=1.0),
        row(y=-1000.0, ball_x=None, ball_y=None, ball_z=None, dt_s=9.0),
    )
    match = match_of(frame)
    assert positioning.ahead_of_ball(match) == {0: pytest.approx(100.0)}
    # The car sits at z = 17 and the ball at z = 92.75 in these frames.
    assert positioning.distance_to_ball(match) == {0: pytest.approx(math.hypot(1000.0, 75.75))}


def test_distance_to_the_ball_is_in_three_dimensions() -> None:
    """3-4-12 from the ball: 13, for 1 s; 100 for 3 s."""
    frame = frames(
        row(x=3.0, y=4.0, z=12.0, ball_x=0.0, ball_y=0.0, ball_z=0.0, dt_s=1.0),
        row(x=100.0, y=0.0, z=0.0, ball_x=0.0, ball_y=0.0, ball_z=0.0, dt_s=3.0),
    )
    assert positioning.distance_to_ball(match_of(frame)) == {0: pytest.approx(313.0 / 4)}


def test_the_last_back_is_the_one_nearest_their_own_goal() -> None:
    """Two blue players over two frames: 0 is deepest on the first, 1 on the second."""
    frame = frames(
        row(player_idx=0, frame=0, y=-3000.0),
        row(player_idx=1, frame=0, y=-1000.0),
        row(player_idx=0, frame=1, y=500.0, dt_s=3.0),
        row(player_idx=1, frame=1, y=-200.0, dt_s=3.0),
    )
    assert positioning.last_back(match_of(frame)) == {
        0: pytest.approx(25.0),
        1: pytest.approx(75.0),
    }


def test_the_last_back_of_orange_is_the_one_with_the_highest_y() -> None:
    frame = frames(
        row(player_idx=0, team=1, y=3000.0),
        row(player_idx=1, team=1, y=1000.0),
    )
    assert positioning.last_back(match_of(frame)) == {
        0: pytest.approx(100.0),
        1: pytest.approx(0.0),
    }


def test_a_demolished_teammate_is_not_the_last_back() -> None:
    """Player 0 is demolished, far back: player 1 is the last back."""
    frame = frames(
        row(player_idx=0, frame=0, y=-5000.0, demolished=True),
        row(player_idx=1, frame=0, y=0.0),
    )
    assert positioning.last_back(match_of(frame)) == {0: None, 1: pytest.approx(100.0)}


def test_the_last_back_is_undefined_alone_in_a_team() -> None:
    """1v1: alone in a team, always last back, so the share says nothing."""
    frame = frames(row(player_idx=0, team=0, y=0.0), row(player_idx=1, team=1, y=0.0))
    assert positioning.last_back(match_of(frame)) == {0: None, 1: None}


def test_teams_do_not_mix_for_the_last_back() -> None:
    frame = frames(
        row(player_idx=0, team=0, y=-1000.0),
        row(player_idx=1, team=0, y=1000.0),
        row(player_idx=2, team=1, y=-5000.0),
        row(player_idx=3, team=1, y=5000.0),
    )
    shares = positioning.last_back(match_of(frame))
    assert shares == {
        0: pytest.approx(100.0),
        1: pytest.approx(0.0),
        2: pytest.approx(0.0),
        3: pytest.approx(100.0),
    }


def test_demolitions_inflicted_and_taken() -> None:
    frame = frames(row(player_idx=0, team=0), row(player_idx=1, team=1))
    match = match_of(
        frame,
        demolitions=[demolition(0, 1), demolition(0, 1), demolition(1, 0), demolition(None, 1)],
    )
    assert positioning.demolitions_inflicted(match) == {0: 2.0, 1: 1.0}
    assert positioning.demolitions_taken(match) == {0: 1.0, 1: 3.0}


def test_no_demolition_is_zero() -> None:
    match = match_of(frames(row()))
    assert positioning.demolitions_inflicted(match) == {0: 0.0}
    assert positioning.demolitions_taken(match) == {0: 0.0}
