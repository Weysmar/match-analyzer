"""Frames and events made by hand, for results worked out by hand."""

from typing import Any, cast

import polars as pl

from ma_schemas import EventsDocument, frames_columns, problems
from rl_analysis.constants import Phase
from rl_analysis.match import Match

_POLARS = {"uint32": pl.UInt32, "uint8": pl.UInt8, "float32": pl.Float32, "boolean": pl.Boolean}


def row(**fields: Any) -> dict[str, Any]:
    """One frame of one player: present, in live play, at the center, with 50 boost."""
    defaults: dict[str, Any] = {
        "frame": 0,
        "time_s": 0.0,
        "dt_s": 1.0,
        "phase": int(Phase.ACTIVE),
        "ball_x": 0.0,
        "ball_y": 0.0,
        "ball_z": 92.75,
        "ball_vx": 0.0,
        "ball_vy": 0.0,
        "ball_vz": 0.0,
        "player_idx": 0,
        "team": 0,
        "present": True,
        "x": 0.0,
        "y": 0.0,
        "z": 17.0,
        "qx": 0.0,
        "qy": 0.0,
        "qz": 0.0,
        "qw": 1.0,
        "vx": 0.0,
        "vy": 0.0,
        "vz": 0.0,
        "boost": 50.0,
        "boost_active": False,
        "jumped": False,
        "double_jumped": False,
        "dodged": False,
        "demolished": False,
    }
    unknown = set(fields) - set(defaults)
    assert not unknown, unknown
    return defaults | fields


def frames(*rows: dict[str, Any]) -> pl.DataFrame:
    """A `frames.parquet` as `rl-parse` writes it, with exactly the schema's columns and types.
    Frames are numbered in the order given, per player, unless a row says otherwise."""
    numbered = []
    counts: dict[int, int] = {}
    for given in rows:
        player = given.get("player_idx", 0)
        counts[player] = counts.get(player, -1) + 1
        numbered.append({"frame": counts[player]} | given)
    schema = {name: _POLARS[kind] for name, kind in frames_columns().items()}
    return pl.DataFrame(numbered, schema=schema)


def pickup(player: int, size: str, y: float, *, phase: Phase = Phase.ACTIVE) -> dict[str, Any]:
    return {
        "frame": 0,
        "time_s": 0.0,
        "phase": int(phase),
        "player_idx": player,
        "pad_index": 0,
        "size": size,
        "x": 0.0,
        "y": y,
        "z": 70.0,
    }


def match_of(frame: pl.DataFrame, **events: Any) -> Match:
    """The match of these frames: the roster is their players, with their teams."""
    roster = [
        {
            "player_idx": int(player),
            "platform": "steam",
            "platform_id": str(player),
            "name": f"Player {player}",
            "team": int(team),
            "anonymized": False,
        }
        for player, team in frame.select("player_idx", "team").unique().sort("player_idx").rows()
    ]
    document: dict[str, Any] = {
        "schema_version": 2,
        "parser_version": "0.2.0",
        "fps": None,
        "playlist_id": 13,
        "duration_s": 300.0,
        "arena_out_of_bounds": False,
        "roster": roster,
        "goals": [],
        "demolitions": [],
        "pad_pickups": [],
        "unresolved_pad_pickups": 0,
        "stat_events": [],
        # Not detected unless a test gives them (T11.1).
        "touches": None,
        "kickoffs": None,
        "fifty_fifties": None,
        "beaten_to_ball": None,
    } | events
    assert problems("events", document) == []
    return Match(frame, cast(EventsDocument, document))
