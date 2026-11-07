"""Frames made by hand, for results worked out by hand."""

from typing import Any

import polars as pl

from ma_schemas import frames_columns
from rl_analysis.constants import Phase

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
    """A `frames.parquet` as `rl-parse` writes it, with exactly the schema's columns and types."""
    schema = {name: _POLARS[kind] for name, kind in frames_columns().items()}
    return pl.DataFrame(list(rows), schema=schema)
