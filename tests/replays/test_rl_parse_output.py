"""The parser's output, read the way the analysis will read it. Run with `just test-replays`."""

import json
import subprocess
from pathlib import Path

import polars as pl
import pytest

ROOT = Path(__file__).parents[2]
BINARY = ROOT / "games/rocket-league/parser/target/release/rl-parse"
REPLAY = ROOT / "tests/fixtures/replays/public/post-eac-ranked-doubles-2026-04-28.replay"

pytestmark = pytest.mark.replays

COLUMNS = {
    "frame": pl.UInt32,
    "time_s": pl.Float32,
    "dt_s": pl.Float32,
    "phase": pl.UInt8,
    "ball_x": pl.Float32,
    "ball_y": pl.Float32,
    "ball_z": pl.Float32,
    "ball_vx": pl.Float32,
    "ball_vy": pl.Float32,
    "ball_vz": pl.Float32,
    "player_idx": pl.UInt8,
    "team": pl.UInt8,
    "present": pl.Boolean,
    "x": pl.Float32,
    "y": pl.Float32,
    "z": pl.Float32,
    "qx": pl.Float32,
    "qy": pl.Float32,
    "qz": pl.Float32,
    "qw": pl.Float32,
    "vx": pl.Float32,
    "vy": pl.Float32,
    "vz": pl.Float32,
    "boost": pl.Float32,
    "boost_active": pl.Boolean,
    "jumped": pl.Boolean,
    "double_jumped": pl.Boolean,
    "dodged": pl.Boolean,
    "demolished": pl.Boolean,
}


@pytest.fixture(scope="module")
def output(tmp_path_factory: pytest.TempPathFactory) -> Path:
    directory = tmp_path_factory.mktemp("frames")
    subprocess.run(
        [str(BINARY), "--frames", "--input", str(REPLAY), "--output-dir", str(directory)],
        check=True,
    )
    return directory


def test_polars_reads_the_exact_schema(output: Path) -> None:
    frames = pl.read_parquet(output / "frames.parquet")
    assert dict(frames.schema) == COLUMNS


def test_every_frame_has_a_row_per_player(output: Path) -> None:
    frames = pl.read_parquet(output / "frames.parquet")
    roster = json.loads((output / "events.json").read_text(encoding="utf-8"))["roster"]
    assert frames["player_idx"].n_unique() == len(roster) == 4
    per_frame = frames.group_by("frame").len()["len"]
    assert per_frame.min() == per_frame.max() == 4


def test_no_platform_id_in_the_frames(output: Path) -> None:
    roster = json.loads((output / "events.json").read_text(encoding="utf-8"))["roster"]
    ids = {player["platform_id"] for player in roster if player["platform_id"]}
    data = (output / "frames.parquet").read_bytes()
    assert ids
    assert not any(platform_id.encode() in data for platform_id in ids)


def test_values_are_usable(output: Path) -> None:
    frames = pl.read_parquet(output / "frames.parquet")
    live = frames.filter(pl.col("phase") == 3)
    assert live.height > 0
    boost = live["boost"].drop_nulls()
    assert boost.is_between(0.0, 100.0).all()
    played = frames.filter(pl.col("player_idx") == 0)["dt_s"].sum()
    events = json.loads((output / "events.json").read_text(encoding="utf-8"))
    assert played == pytest.approx(events["duration_s"], rel=0.02)
