"""Touch metrics (T11.4), on frames and touches made by hand."""

from typing import Any

import pytest

from rl_analysis import touches
from rl_analysis.constants import HIGH_AIR_MIN_Z, Phase

from .synthetic import frames, match_of, row


def touch(
    frame: int,
    player: int,
    *,
    speed_change: float = 500.0,
    team: int = 0,
    kind: str | None = None,
) -> dict[str, Any]:
    return {
        "frame": frame,
        "time_s": float(frame),
        "player_idx": player,
        "team": team,
        "ball_speed_change": speed_change,
        "kind": kind,
        "height_band": None,
        "surface": None,
        "contested": False,
    }


def two_players(seconds: int = 60, **fields: Any) -> list[dict[str, Any]]:
    """Two players in live play, one frame per second."""
    rows = []
    for second in range(seconds):
        rows.append(row(frame=second, time_s=float(second), player_idx=0, **fields))
        rows.append(row(frame=second, time_s=float(second), player_idx=1, team=1))
    return rows


def test_touches_are_counted_per_player() -> None:
    match = match_of(
        frames(*two_players()), touches=[touch(1, 0), touch(2, 0), touch(5, 1, team=1)]
    )
    assert touches.count(match) == {0: 2.0, 1: 1.0}


def test_a_player_who_never_touched_counts_zero() -> None:
    match = match_of(frames(*two_players()), touches=[touch(1, 0)])
    assert touches.count(match)[1] == 0.0


def test_without_detections_every_touch_metric_is_unknown() -> None:
    """A match parsed before rl-parse 0.2.0: not detected is not zero."""
    match = match_of(frames(*two_players()), touches=None)
    for metric in (touches.count, touches.per_minute, touches.share_aerial, touches.share_hard):
        assert metric(match) == {0: None, 1: None}


def test_the_rate_is_per_minute_of_live_play() -> None:
    # 60 s of live play, then 60 s of countdown that do not count.
    rows = two_players(60) + [
        row(frame=60 + s, time_s=60.0 + s, player_idx=p, team=p, phase=int(Phase.COUNTDOWN))
        for s in range(60)
        for p in (0, 1)
    ]
    match = match_of(frames(*rows), touches=[touch(f, 0) for f in range(1, 31)])
    assert touches.per_minute(match)[0] == pytest.approx(30.0)


def test_time_while_demolished_does_not_count_for_the_rate() -> None:
    rows = two_players(60)
    for given in rows:
        if given["player_idx"] == 0 and given["frame"] >= 30:
            given["demolished"] = True
    match = match_of(frames(*rows), touches=[touch(1, 0)])
    assert touches.per_minute(match)[0] == pytest.approx(2.0)


def test_no_live_time_gives_no_rate() -> None:
    rows = [
        row(frame=s, time_s=float(s), player_idx=p, team=p, phase=int(Phase.COUNTDOWN))
        for s in range(10)
        for p in (0, 1)
    ]
    match = match_of(frames(*rows), touches=[])
    assert touches.per_minute(match) == {0: None, 1: None}


def test_an_aerial_touch_is_one_made_in_high_air() -> None:
    rows = two_players(10)
    for given in rows:
        if given["player_idx"] == 0 and given["frame"] == 4:
            given["z"] = HIGH_AIR_MIN_Z
        if given["player_idx"] == 0 and given["frame"] == 6:
            given["z"] = HIGH_AIR_MIN_Z - 1
    match = match_of(frames(*rows), touches=[touch(4, 0), touch(6, 0), touch(8, 0), touch(9, 0)])
    assert touches.share_aerial(match)[0] == pytest.approx(25.0)


def test_the_height_comes_from_the_frame_before_when_the_touch_falls_between_two() -> None:
    rows = [row(frame=f, time_s=float(f), z=HIGH_AIR_MIN_Z + 10) for f in (0, 10)]
    match = match_of(frames(*rows), touches=[touch(5, 0)])
    assert touches.share_aerial(match)[0] == pytest.approx(100.0)


def test_no_touch_gives_no_share() -> None:
    match = match_of(frames(*two_players()), touches=[touch(1, 0)])
    assert touches.share_aerial(match)[1] is None
    assert touches.share_hard(match)[1] is None


def test_a_hard_touch_changes_the_ball_speed_by_900_or_more() -> None:
    match = match_of(
        frames(*two_players()),
        touches=[
            touch(1, 0, speed_change=899.9),
            touch(2, 0, speed_change=900.0),
            touch(3, 0, speed_change=2500.0),
            touch(4, 0, speed_change=100.0),
        ],
    )
    assert touches.share_hard(match)[0] == pytest.approx(50.0)


def test_a_carry_is_never_a_hard_touch() -> None:
    """subtr-actor tags a controlled touch `control`, whatever the ball's speed change."""
    match = match_of(
        frames(*two_players()),
        touches=[
            touch(1, 0, speed_change=1500.0, kind="control"),
            touch(2, 0, speed_change=1500.0, kind="hard_hit"),
        ],
    )
    assert touches.share_hard(match)[0] == pytest.approx(50.0)


def test_teams_are_measured_alike() -> None:
    match = match_of(
        frames(*two_players()),
        touches=[touch(1, 0, speed_change=1000.0), touch(2, 1, speed_change=1000.0, team=1)],
    )
    assert touches.share_hard(match) == {0: 100.0, 1: 100.0}
