"""The schemas against hand-written documents: what must pass, and what must not."""

import copy
from typing import Any, get_type_hints

import pytest

import ma_schemas
from ma_schemas import types


def valid_header() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "parser_version": "0.1.0",
        "game_build": "261031.63733.533021",
        "build_id": 1,
        "changelist": 2,
        "replay_version": {"major": 868, "minor": 34, "net": 12},
        "game_class": "TAGame.Replay_Soccar_TA",
        "match_guid": "abc",
        "replay_id": "def",
        "map": "cs_p",
        "played_at": "2026-11-06T15:23:43Z",
        "played_at_source": "epoch",
        "duration_s": 310.5,
        "match_type": "Online",
        "playlist": None,
        "team_size": 2,
        "score": {"blue": 1, "orange": 0},
        "goals": [{"frame": 10, "time_s": 0.3, "player_name": "a", "team": 0}],
        "players": [
            {
                "platform": "epic",
                "platform_id": "abc123",
                "name": "a",
                "team": 0,
                "score": 100,
                "goals": 1,
                "assists": 0,
                "saves": 0,
                "shots": 1,
                "is_bot": False,
            }
        ],
    }


def valid_events() -> dict[str, Any]:
    return events_v1() | {
        "schema_version": 2,
        "parser_version": "0.2.0",
        "touches": [
            {
                "frame": 1,
                "time_s": 2.0,
                "player_idx": 0,
                "team": 1,
                "ball_speed_change": 900.5,
                "kind": "hard_hit",
                "height_band": "ground",
                "surface": "ground",
                "contested": False,
            }
        ],
        "kickoffs": [
            {
                "start_frame": 0,
                "start_time_s": 0.0,
                "end_frame": 40,
                "end_time_s": 4.5,
                "kickoff_type": "diagonal",
                "first_touch_frame": 30,
                "first_touch_time_s": 3.1,
                "first_touch_player_idx": 0,
                "winner_team": 1,
                "outcome": "win",
                "goal": False,
                "time_to_goal_s": None,
                "takers": [
                    {
                        "player_idx": 0,
                        "team": 1,
                        "time_to_ball_s": 2.4,
                        "start_boost": 33.3,
                        "boost_used": 20.0,
                    }
                ],
            }
        ],
        "fifty_fifties": [
            {
                "start_frame": 30,
                "start_time_s": 3.1,
                "resolve_frame": 40,
                "resolve_time_s": 3.5,
                "is_kickoff": True,
                "blue_player_idx": None,
                "orange_player_idx": 0,
                "winner_team": None,
                "possession_team": 1,
            }
        ],
        "beaten_to_ball": [
            {
                "frame": 50,
                "time_s": 6.0,
                "player_idx": 0,
                "winner_idx": None,
                "team": 1,
                "distance_at_touch": 420.0,
                "margin_s": 0.3,
                "approach_speed": 1200.0,
            }
        ],
    }


def events_v1() -> dict[str, Any]:
    """As parsers before 0.2.0 wrote it: no detections."""
    return {
        "schema_version": 1,
        "parser_version": "0.1.0",
        "fps": None,
        "playlist_id": 11,
        "duration_s": 310.5,
        "arena_out_of_bounds": False,
        "roster": [
            {
                "player_idx": 0,
                "platform": "steam",
                "platform_id": "42",
                "name": "a",
                "team": 1,
                "anonymized": False,
            }
        ],
        "goals": [
            {
                "frame": 1,
                "time_s": 2.0,
                "team": 0,
                "player_idx": None,
                "score_blue": 1,
                "score_orange": 0,
            }
        ],
        "demolitions": [
            {
                "frame": 1,
                "time_s": 2.0,
                "attacker_idx": 0,
                "victim_idx": None,
                "x": 0.0,
                "y": 0.0,
                "z": 17.0,
            }
        ],
        "pad_pickups": [
            {
                "frame": 1,
                "time_s": 2.0,
                "phase": 3,
                "player_idx": 0,
                "pad_index": 4,
                "size": "big",
                "x": 0.0,
                "y": 0.0,
                "z": 73.0,
            }
        ],
        "unresolved_pad_pickups": 0,
        "stat_events": [{"frame": 1, "time_s": 2.0, "player_idx": 0, "kind": "shot"}],
    }


def test_valid_documents_pass() -> None:
    assert ma_schemas.problems("header", valid_header()) == []
    assert ma_schemas.problems("events", valid_events()) == []


def test_nulls_where_the_parser_writes_them() -> None:
    header = valid_header()
    for key in ("game_build", "match_guid", "map", "played_at", "played_at_source", "duration_s"):
        header[key] = None
    header["replay_version"]["net"] = None
    header["goals"][0]["player_name"] = None
    header["players"][0]["platform_id"] = None
    assert ma_schemas.problems("header", header) == []


@pytest.mark.parametrize("key", sorted(ma_schemas.load_schema("header")["required"]))
def test_every_required_header_field_is_enforced(key: str) -> None:
    header = valid_header()
    del header[key]
    assert ma_schemas.problems("header", header) == ["(root): required"]


@pytest.mark.parametrize("key", sorted(ma_schemas.load_schema("events")["required"]))
def test_every_required_events_field_is_enforced(key: str) -> None:
    events = valid_events()
    del events[key]
    assert ma_schemas.problems("events", events) == ["(root): required"]


@pytest.mark.parametrize(
    ("change", "where"),
    [
        (lambda d: d.update(schema_version=2), "schema_version: const"),
        (lambda d: d.update(played_at="yesterday"), "played_at: pattern"),
        (lambda d: d.update(played_at_source="guess"), "played_at_source: enum"),
        (lambda d: d.update(duration_s=-1), "duration_s: minimum"),
        (lambda d: d["score"].update(blue="3"), "score/blue: type"),
        (lambda d: d["goals"][0].update(team=2), "goals/0/team: enum"),
        (lambda d: d["players"][0].update(platform="stadia"), "players/0/platform: enum"),
        (lambda d: d["players"][0].update(platform_id=""), "players/0/platform_id: minLength"),
    ],
)
def test_header_counter_examples(change: Any, where: str) -> None:
    header = valid_header()
    change(header)
    assert ma_schemas.problems("header", header) == [where]


@pytest.mark.parametrize(
    ("change", "where"),
    [
        (lambda d: d.update(fps=0), "fps: exclusiveMinimum"),
        (lambda d: d.update(arena_out_of_bounds="no"), "arena_out_of_bounds: type"),
        (lambda d: d["roster"][0].update(team=None), "roster/0/team: enum"),
        (lambda d: d["roster"][0].update(player_idx=-1), "roster/0/player_idx: minimum"),
        (lambda d: d["goals"][0].update(player_idx="0"), "goals/0/player_idx: type"),
        (lambda d: d["pad_pickups"][0].update(size="medium"), "pad_pickups/0/size: enum"),
        (lambda d: d["pad_pickups"][0].update(phase=5), "pad_pickups/0/phase: enum"),
        (lambda d: d["stat_events"][0].update(kind="goal"), "stat_events/0/kind: enum"),
        (lambda d: d.update(schema_version=3), "schema_version: const"),
        (lambda d: d["touches"][0].update(team=None), "touches/0/team: enum"),
        (lambda d: d["touches"][0].update(contested="no"), "touches/0/contested: type"),
        (
            lambda d: d["kickoffs"][0].update(kickoff_type="wavedash"),
            "kickoffs/0/kickoff_type: enum",
        ),
        (lambda d: d["kickoffs"][0].update(outcome="loss"), "kickoffs/0/outcome: enum"),
        (
            lambda d: d["kickoffs"][0]["takers"][0].update(player_idx=None),
            "kickoffs/0/takers/0/player_idx: type",
        ),
        (
            lambda d: d["fifty_fifties"][0].update(winner_team=2),
            "fifty_fifties/0/winner_team: enum",
        ),
        (lambda d: d["beaten_to_ball"][0].update(margin_s=None), "beaten_to_ball/0/margin_s: type"),
    ],
)
def test_events_counter_examples(change: Any, where: str) -> None:
    events = valid_events()
    change(events)
    assert ma_schemas.problems("events", events) == [where]


def test_unknown_fields_are_accepted() -> None:
    header = valid_header()
    header["from_a_future_patch"] = True
    header["players"][0]["from_a_future_patch"] = True
    assert ma_schemas.problems("header", header) == []


def test_errors_never_quote_a_value() -> None:
    header = valid_header()
    header["players"][0]["name"] = 12345
    header["players"][0]["platform"] = "some-player-secret"
    with pytest.raises(ma_schemas.InvalidDocumentError) as error:
        ma_schemas.parse_header(header)
    assert "some-player-secret" not in str(error.value)
    assert "12345" not in str(error.value)


def test_parse_returns_the_document() -> None:
    header = valid_header()
    assert ma_schemas.parse_header(copy.deepcopy(header)) == header
    events = valid_events()
    assert ma_schemas.parse_events(copy.deepcopy(events)) == events


def test_failed_detections_are_null() -> None:
    events = valid_events() | dict.fromkeys(ma_schemas.DETECTIONS)
    assert ma_schemas.problems("events", events) == []


def test_a_version_1_document_reads_as_version_2_without_detections() -> None:
    """Matches parsed before parser 0.2.0 keep working, as not detected (T11.2)."""
    old = events_v1()
    parsed = ma_schemas.parse_events(old)
    assert parsed["schema_version"] == 2
    assert [parsed[key] for key in ma_schemas.DETECTIONS] == [None] * 4  # type: ignore[literal-required]
    assert parsed["roster"] == old["roster"]
    # The caller's document is left alone.
    assert old["schema_version"] == 1
    assert "touches" not in old


def test_a_version_1_document_with_detections_is_not_upgraded() -> None:
    """Version 1 never had them: such a document is broken, not old."""
    odd = events_v1() | {"touches": []}
    with pytest.raises(ma_schemas.InvalidDocumentError):
        ma_schemas.parse_events(odd)


def test_frames_problems_detect_every_difference() -> None:
    columns = ma_schemas.frames_columns()
    assert ma_schemas.frames_problems(columns) == []

    missing = {name: kind for name, kind in columns.items() if name != "boost"}
    assert ma_schemas.frames_problems(missing) == ["boost: missing"]

    assert ma_schemas.frames_problems({**columns, "extra": "uint8"}) == ["extra: unexpected"]
    assert ma_schemas.frames_problems({**columns, "boost": "uint8"}) == [
        "boost: uint8 instead of float32"
    ]
    reordered = dict(reversed(list(columns.items())))
    assert ma_schemas.frames_problems(reordered) == ["columns are in another order"]


def test_frames_schema_contract() -> None:
    schema = ma_schemas.load_schema("frames")
    assert schema["schema_version"] == 1
    columns = schema["columns"]
    assert len({column["name"] for column in columns}) == len(columns) == 29
    assert {column["type"] for column in columns} == {"uint32", "uint8", "float32", "boolean"}
    names = {column["name"] for column in columns}
    assert not names & {"platform", "platform_id", "name", "player_id"}


def _object_at(schema: dict[str, Any], *path: str) -> dict[str, Any]:
    node = schema
    for step in path:
        node = node["items"] if step == "[]" else node["properties"][step]
    return node


@pytest.mark.parametrize(
    ("typed", "kind", "path"),
    [
        (types.HeaderDocument, "header", ()),
        (types.ReplayVersion, "header", ("replay_version",)),
        (types.Score, "header", ("score",)),
        (types.HeaderGoal, "header", ("goals", "[]")),
        (types.HeaderPlayer, "header", ("players", "[]")),
        (types.EventsDocument, "events", ()),
        (types.RosterPlayer, "events", ("roster", "[]")),
        (types.Goal, "events", ("goals", "[]")),
        (types.Demolition, "events", ("demolitions", "[]")),
        (types.PadPickup, "events", ("pad_pickups", "[]")),
        (types.StatEvent, "events", ("stat_events", "[]")),
        (types.Touch, "events", ("touches", "[]")),
        (types.Kickoff, "events", ("kickoffs", "[]")),
        (types.KickoffTaker, "events", ("kickoffs", "[]", "takers", "[]")),
        (types.FiftyFifty, "events", ("fifty_fifties", "[]")),
        (types.BeatenToBall, "events", ("beaten_to_ball", "[]")),
    ],
)
def test_typed_dicts_follow_the_schemas(typed: Any, kind: str, path: tuple[str, ...]) -> None:
    schema = _object_at(ma_schemas.load_schema(kind), *path)
    assert set(get_type_hints(typed)) == set(schema["properties"]) == set(schema["required"])
