"""Duels and beaten to the ball (T13.3), on events made by hand."""

from typing import Any

import pytest

from rl_analysis import duels

from .synthetic import frames, match_of, row

# Players 0 and 2 for blue, 1 and 3 for orange.
TEAM = {0: 0, 1: 1, 2: 0, 3: 1}


def four() -> Any:
    return frames(*[row(player_idx=player, team=team) for player, team in TEAM.items()])


def duel(
    blue: int,
    orange: int,
    possession: int | None,
    *,
    kickoff: bool = False,
    winner: int | None = None,
) -> dict[str, Any]:
    return {
        "start_frame": 10,
        "start_time_s": 10.0,
        "resolve_frame": 15,
        "resolve_time_s": 10.4,
        "is_kickoff": kickoff,
        "blue_player_idx": blue,
        "orange_player_idx": orange,
        "winner_team": winner,
        "possession_team": possession,
    }


def beaten_event(player: int, winner: int) -> dict[str, Any]:
    return {
        "frame": 20,
        "time_s": 20.0,
        "player_idx": player,
        "winner_idx": winner,
        "team": TEAM[player],
        "distance_at_touch": 300.0,
        "margin_s": 0.1,
        "approach_speed": 1500.0,
    }


def played(**events: Any) -> Any:
    return match_of(four(), **({"fifty_fifties": [], "beaten_to_ball": []} | events))


def test_each_player_of_a_duel_contested_it() -> None:
    match = played(fifty_fifties=[duel(0, 1, 0), duel(0, 3, 1), duel(2, 1, None)])
    assert duels.count(match) == {0: 2.0, 1: 2.0, 2: 1.0, 3: 1.0}


def test_kickoff_duels_count_too() -> None:
    match = played(fifty_fifties=[duel(0, 1, 0, kickoff=True)])
    assert duels.count(match)[0] == 1.0


def test_a_duel_is_won_by_the_team_with_the_ball_after_it() -> None:
    match = played(fifty_fifties=[duel(0, 1, 0), duel(0, 1, 1), duel(0, 1, None)])
    shares = duels.won_share(match)
    assert shares[0] == pytest.approx(100 / 3)
    assert shares[1] == pytest.approx(100 / 3)
    assert shares[2] is None


def test_the_contact_winner_does_not_decide() -> None:
    """subtr-actor's `winner_team` judges the contact; the plan, the ball afterwards."""
    match = played(fifty_fifties=[duel(0, 1, possession=1, winner=0)])
    assert duels.won_share(match) == {0: 0.0, 1: 100.0, 2: None, 3: None}


def test_beaten_to_the_ball_counts_for_the_beaten_player() -> None:
    match = played(beaten_to_ball=[beaten_event(0, 1), beaten_event(0, 3), beaten_event(3, 2)])
    assert duels.beaten(match) == {0: 2.0, 1: 0.0, 2: 0.0, 3: 1.0}


def test_without_detections_nothing_is_known() -> None:
    match = match_of(four(), fifty_fifties=None, beaten_to_ball=None)
    for metric in (duels.count, duels.won_share, duels.beaten):
        assert metric(match) == dict.fromkeys(TEAM)


def test_no_duel_is_zero_contested_and_no_share() -> None:
    match = played()
    assert duels.count(match) == dict.fromkeys(TEAM, 0.0)
    assert duels.won_share(match) == dict.fromkeys(TEAM)
    assert duels.beaten(match) == dict.fromkeys(TEAM, 0.0)
