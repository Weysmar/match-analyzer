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
    ],
)
def test_typed_dicts_follow_the_schemas(typed: Any, kind: str, path: tuple[str, ...]) -> None:
    schema = _object_at(ma_schemas.load_schema(kind), *path)
    assert set(get_type_hints(typed)) == set(schema["properties"]) == set(schema["required"])
