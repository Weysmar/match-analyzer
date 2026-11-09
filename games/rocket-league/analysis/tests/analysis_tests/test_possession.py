"""Possession (T11.5, T11.6), on touches made by hand. Frames every half second over 20 s of live
play, so 20 s are tracked unless a test says otherwise: one second of possession is 5 %."""

from typing import Any

import pytest

from rl_analysis import possession
from rl_analysis.constants import Phase
from rl_analysis.possession import Segment

from .synthetic import frames, match_of, row

STEP_S = 0.5
END_S = 20.0
# Players 0 and 2 play for blue (team 0), 1 for orange.
TEAM = {0: 0, 1: 1, 2: 0}


def at(time_s: float, player: int) -> dict[str, Any]:
    """A touch at this time, on the frame there."""
    return {
        "frame": round(time_s / STEP_S),
        "time_s": time_s,
        "player_idx": player,
        "team": TEAM[player],
        "ball_speed_change": 500.0,
        "kind": None,
        "height_band": None,
        "surface": None,
        "contested": False,
    }


def match(
    *touches: dict[str, Any], phases: dict[int, Phase] | None = None, players: int = 2
) -> Any:
    rows = []
    for index in range(round(END_S / STEP_S) + 1):
        phase = (phases or {}).get(index, Phase.ACTIVE)
        for player in range(players):
            rows.append(
                row(
                    frame=index,
                    time_s=index * STEP_S,
                    dt_s=STEP_S,
                    phase=int(phase),
                    player_idx=player,
                    team=TEAM[player],
                )
            )
    return match_of(frames(*rows), touches=list(touches))


def labels(*touches: dict[str, Any], **options: Any) -> list[tuple[float, float, int | None]]:
    resolved = possession.resolve(match(*touches, **options))
    assert resolved is not None
    return [(s.start_s, s.end_s, s.team) for s in resolved.segments]


def test_a_lone_touch_grants_nothing() -> None:
    assert labels(at(1.0, 0)) == [(0.0, END_S, None)]


def test_a_second_touch_confirms_from_the_first() -> None:
    assert labels(at(1.0, 0), at(2.0, 0)) == [(0.0, 1.0, None), (1.0, 2.0, 0), (2.0, END_S, None)]
    assert possession.team_share(match(at(1.0, 0), at(2.0, 0))) == {0: 5.0, 1: 0.0}


def test_touches_within_the_window_keep_the_ball() -> None:
    assert (1.0, 6.0, 0) in labels(at(1.0, 0), at(3.5, 0), at(6.0, 0))


def test_a_gap_over_the_window_ends_the_possession_at_the_last_touch() -> None:
    # The frame at 5.5 s, 3.5 s after the last touch, finds it expired.
    assert labels(at(1.0, 0), at(2.0, 0), at(6.0, 0)) == [
        (0.0, 1.0, None),
        (1.0, 2.0, 0),
        # The touch at 6 s is alone again: nothing until a follow-up.
        (2.0, END_S, None),
    ]


def test_expiry_is_only_seen_on_a_frame_without_touch() -> None:
    """As in subtr-actor: a touch on the first frame past the window still counts as a follow-up,
    since the expiry is only checked when nobody touches the ball."""
    assert (1.0, 5.5, 0) in labels(at(1.0, 0), at(2.0, 0), at(5.5, 0))


def test_a_confirmed_challenge_is_a_turnover() -> None:
    touches = (at(1.0, 0), at(2.0, 0), at(3.0, 1), at(4.0, 1))
    assert labels(*touches) == [
        (0.0, 1.0, None),
        (1.0, 2.0, 0),
        (2.0, 3.0, None),
        (3.0, 4.0, 1),
        (4.0, END_S, None),
    ]
    played = match(*touches)
    assert possession.turnovers_lost(played) == {0: 1.0, 1: 0.0}
    assert possession.turnovers_won(played) == {0: 0.0, 1: 1.0}


def test_a_repelled_challenge_keeps_the_possession_whole() -> None:
    touches = (at(1.0, 0), at(2.0, 0), at(2.5, 1), at(3.0, 0))
    assert (1.0, 3.0, 0) in labels(*touches)
    assert possession.turnovers_lost(match(*touches)) == {0: 0.0, 1: 0.0}


def test_a_challenge_with_no_follow_up_leaves_the_ball_loose() -> None:
    touches = (at(1.0, 0), at(2.0, 0), at(2.5, 1))
    assert labels(*touches) == [(0.0, 1.0, None), (1.0, 2.0, 0), (2.0, END_S, None)]
    assert possession.turnovers_won(match(*touches)) == {0: 0.0, 1: 0.0}


def test_a_contested_loose_ball_stays_loose() -> None:
    assert labels(at(1.0, 0), at(1.0, 1)) == [(0.0, END_S, None)]


def test_a_contested_touch_challenges_the_holder_and_a_second_one_turns_it_over() -> None:
    touches = (at(1.0, 0), at(2.0, 0), at(3.0, 0), at(3.0, 1), at(4.0, 0), at(4.0, 1))
    assert labels(*touches) == [
        (0.0, 1.0, None),
        # The contested touch at 3 s is the holder's last.
        (1.0, 3.0, 0),
        (3.0, 4.0, 1),
        (4.0, END_S, None),
    ]


def test_only_live_play_is_tracked_and_a_stretch_ends_the_possession() -> None:
    # A countdown from 10 s to 14.5 s: frames 20 to 29.
    countdown = dict.fromkeys(range(20, 30), Phase.COUNTDOWN)
    played = match(at(8.0, 0), at(9.5, 0), phases=countdown)
    resolved = possession.resolve(played)
    assert resolved is not None
    # Live from 0 to 10 s, then from 15 to 20 s; the possession stops at its last touch.
    assert resolved.tracked_s == pytest.approx(15.0)
    assert (8.0, 9.5, 0) in [(s.start_s, s.end_s, s.team) for s in resolved.segments]
    assert possession.team_share(played)[0] == pytest.approx(100 * 1.5 / 15)


def test_the_player_share_splits_the_possession_between_touchers() -> None:
    played = match(at(1.0, 0), at(2.0, 2), at(3.0, 0), players=3)
    shares = possession.player_share(played)
    assert shares == {0: pytest.approx(5.0), 1: 0.0, 2: pytest.approx(5.0)}
    assert sum(v or 0.0 for v in shares.values()) == pytest.approx(
        possession.team_share(played)[0] or 0.0
    )


def test_the_holder_of_a_segment_is_its_last_toucher() -> None:
    resolved = possession.resolve(match(at(1.0, 0), at(2.0, 2), players=3))
    assert resolved is not None
    assert Segment(1.0, 2.0, 0, 2) in resolved.segments


def test_without_detections_possession_is_unknown() -> None:
    played = match_of(frames(row(player_idx=0), row(player_idx=1, team=1)), touches=None)
    assert possession.resolve(played) is None
    assert possession.team_share(played) == {0: None, 1: None}
    for metric in (
        possession.player_share,
        possession.turnovers_lost,
        possession.turnovers_won,
    ):
        assert metric(played) == {0: None, 1: None}


def test_no_touch_is_no_possession_at_all() -> None:
    played = match()
    assert possession.team_share(played) == {0: 0.0, 1: 0.0}
    assert possession.turnovers_lost(played) == {0: 0.0, 1: 0.0}


def test_no_live_play_gives_no_share() -> None:
    countdown = dict.fromkeys(range(round(END_S / STEP_S) + 1), Phase.COUNTDOWN)
    played = match(phases=countdown)
    assert possession.team_share(played) == {0: None, 1: None}
    assert possession.player_share(played) == {0: None, 1: None}


def test_teams_are_resolved_alike() -> None:
    blue = possession.team_share(match(at(1.0, 0), at(2.0, 0)))
    orange = possession.team_share(match(at(1.0, 1), at(2.0, 1)))
    assert blue[0] == orange[1]
    assert blue[1] == orange[0]
