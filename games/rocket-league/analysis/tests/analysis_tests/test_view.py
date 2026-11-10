"""The 2D view's document (T12.1), on frames made by hand: values at given times, the encoding, and
what it must never hold."""

import json
from typing import Any

import pytest

from ma_schemas import problems
from rl_analysis import view
from rl_analysis.constants import Phase
from rl_analysis.view import BOOSTING, DEMOLISHED, PRESENT

from .synthetic import frames, match_of, row

IDS = {0: 41, 1: 42}


def two_cars(seconds: int = 4, **blue: Any) -> list[dict[str, Any]]:
    """Two cars, one frame per second: blue drives along +x at 1000 uu/s, orange stays put."""
    rows = []
    for second in range(seconds + 1):
        fields = {"x": 1000.0 * second, "ball_x": 100.0 * second} | {
            key: value(second) if callable(value) else value for key, value in blue.items()
        }
        rows.append(row(frame=second, time_s=float(second), player_idx=0, **fields))
        rows.append(
            row(
                frame=second,
                time_s=float(second),
                player_idx=1,
                team=1,
                y=500.0,
                ball_x=100.0 * second,
            )
        )
    return rows


def decoded(document: dict[str, Any]) -> dict[str, Any]:
    copy: dict[str, Any] = json.loads(json.dumps(document))
    copy["clock_ds"] = view.undelta(copy["clock_ds"])
    for axis in "xyz":
        copy["ball"][axis] = view.undelta(copy["ball"][axis])
        for player in copy["players"]:
            player[axis] = view.undelta(player[axis])
    return copy


def built(*rows: dict[str, Any], **events: Any) -> dict[str, Any]:
    return view.build(match_of(frames(*rows), **events), IDS)


def test_the_document_follows_its_schema() -> None:
    assert problems("match2d", built(*two_cars())) == []


def test_samples_sit_on_a_regular_grid_from_the_first_frame_to_the_last() -> None:
    document = built(*two_cars(4))
    assert document["rate_hz"] == view.RATE_HZ == 15
    assert document["start_s"] == 0.0
    assert document["samples"] == 4 * 15 + 1
    assert len(document["phase"]) == len(document["players"][0]["flags"]) == document["samples"]


def test_positions_are_interpolated_between_frames() -> None:
    document = decoded(built(*two_cars()))
    blue = next(player for player in document["players"] if player["id"] == 41)
    # 1.4 s is sample 21: 1400 uu along x, the ball at 140.
    assert blue["x"][21] == 1400
    assert document["ball"]["x"][21] == 140
    orange = next(player for player in document["players"] if player["id"] == 42)
    assert set(orange["y"]) == {500}


def test_delta_round_trips() -> None:
    values = [5, 7, 7, -3, 0]
    assert view.delta(values) == [5, 2, 0, -10, 3]
    assert view.undelta(view.delta(values)) == values


def test_players_are_named_by_their_match_player_id_and_nothing_else() -> None:
    document = built(*two_cars())
    assert [player["id"] for player in document["players"]] == [41, 42]
    text = json.dumps(document)
    for name in ("Player 0", "Player 1", "platform", "steam", "name"):
        assert name not in text


def test_a_player_without_an_id_is_left_out() -> None:
    document = view.build(match_of(frames(*two_cars())), {0: 41})
    assert [player["id"] for player in document["players"]] == [41]


def test_flags_say_shown_demolished_and_boosting() -> None:
    document = built(
        *two_cars(
            demolished=lambda second: second == 2,
            boost_active=lambda second: second == 3,
        )
    )
    flags = next(player for player in document["players"] if player["id"] == 41)["flags"]
    assert flags[0] == PRESENT
    assert flags[2 * 15] == DEMOLISHED
    assert flags[3 * 15] == PRESENT | BOOSTING


def test_a_demolished_car_keeps_its_last_shown_position() -> None:
    document = decoded(built(*two_cars(demolished=lambda second: second == 2)))
    blue = next(player for player in document["players"] if player["id"] == 41)
    # Between 1 s and 3 s the car is only shown at 1 s and 3 s: the line between them.
    assert blue["x"][2 * 15] == 2000


def test_the_heading_comes_from_the_quaternion() -> None:
    # A quarter turn about z: facing +y.
    half = 2**-0.5
    document = built(*two_cars(qz=half, qw=half))
    yaw = next(player for player in document["players"] if player["id"] == 41)["yaw"]
    assert set(yaw) == {90}


def test_the_clock_runs_in_live_play_only() -> None:
    countdown = {0, 1}
    rows = [
        given | {"phase": int(Phase.COUNTDOWN)} if given["frame"] in countdown else given
        for given in two_cars(4)
    ]
    clock = decoded(built(*rows))["clock_ds"]
    assert clock[0] == 0
    assert clock[15] == 0
    # Live from the frame at 2 s, each frame counting its dt of 1 s: 3 s by the end.
    assert clock[-1] == 30
    assert clock == sorted(clock)


def test_events_name_players_by_id() -> None:
    touches = [
        {
            "frame": 1,
            "time_s": 1.0,
            "player_idx": 1,
            "team": 1,
            "ball_speed_change": 500.0,
            "kind": None,
            "height_band": None,
            "surface": None,
            "contested": False,
        }
    ]
    goal = {
        "frame": 3,
        "time_s": 3.0,
        "team": 0,
        "player_idx": 0,
        "score_blue": 1,
        "score_orange": 0,
    }
    demo = {
        "frame": 2,
        "time_s": 2.0,
        "attacker_idx": 1,
        "victim_idx": 0,
        "x": 0.0,
        "y": 0.0,
        "z": 17.0,
    }
    document = built(*two_cars(), touches=touches, goals=[goal], demolitions=[demo])
    assert document["touches"] == [{"time_s": 1.0, "player": 42}]
    # The clock at the end of the goal's frame: four live frames of 1 s each.
    assert document["goals"] == [{"time_s": 3.0, "clock_s": 4.0, "team": 0, "player": 41}]
    assert document["demolitions"] == [{"time_s": 2.0, "attacker": 42, "victim": 41}]


def test_touches_not_detected_stay_null() -> None:
    document = built(*two_cars(), touches=None)
    assert document["touches"] is None
    assert document["situations"] is None


def touched(frame: int, player: int) -> dict[str, Any]:
    return {
        "frame": frame,
        "time_s": float(frame),
        "player_idx": player,
        "team": player,
        "ball_speed_change": 500.0,
        "kind": None,
        "height_band": None,
        "surface": None,
        "contested": False,
    }


def test_a_turnover_is_a_situation_at_the_winners_first_touch() -> None:
    """Blue holds the ball with two touches, orange takes it with two: one turnover."""
    touches = [touched(0, 0), touched(1, 0), touched(2, 1), touched(3, 1)]
    document = built(*two_cars(), touches=touches)
    assert problems("match2d", document) == []
    assert document["situations"] == [
        {"kind": "turnover", "time_s": 2.0, "team": 1, "players": [42, 41]}
    ]


def test_no_turnover_is_no_situation() -> None:
    document = built(*two_cars(), touches=[touched(0, 0), touched(1, 0)])
    assert document["situations"] == []


@pytest.mark.parametrize("missing", ["ball_x", "x"])
def test_holes_in_the_frames_do_not_break_the_document(missing: str) -> None:
    rows = [given | {missing: None} if given["frame"] == 2 else given for given in two_cars()]
    assert problems("match2d", built(*rows)) == []


def test_a_goal_context_stays_out_of_the_view() -> None:
    """Goals are marked on the cursor already; their context is for the match sheet."""
    goal = {
        "frame": 3,
        "time_s": 3.0,
        "team": 1,
        "player_idx": 1,
        "score_blue": 0,
        "score_orange": 1,
    }
    document = built(*two_cars(), touches=[touched(2, 1)], goals=[goal])
    assert problems("match2d", document) == []
    assert document["situations"] == []
