"""The parser's real output against the schemas, on every replay of this machine."""

import json
import subprocess
from pathlib import Path

import polars as pl
import pytest

import ma_schemas

ROOT = Path(__file__).parents[2]
BINARY = ROOT / "games/rocket-league/parser/target/release/rl-parse"
REPLAYS = ROOT / "tests/fixtures/replays"
UNSUPPORTED_MODE = 14

pytestmark = pytest.mark.replays

PARQUET_TYPES = {"UInt32": "uint32", "UInt8": "uint8", "Float32": "float32", "Boolean": "boolean"}


def replays() -> list[Path]:
    files = sorted(REPLAYS.glob("*/*.replay"))
    # "Copie" files are exact duplicates; one of each is enough.
    return [path for path in files if " - Copie" not in path.name]


def run(*arguments: str) -> int:
    return subprocess.run(
        [str(BINARY), *arguments], stderr=subprocess.DEVNULL, check=False
    ).returncode


def test_the_corpus_is_there() -> None:
    assert replays(), "no replay: run `just corpus-fetch`"


@pytest.mark.parametrize("replay", replays(), ids=lambda path: path.name)
def test_output_matches_the_schemas(replay: Path, tmp_path: Path) -> None:
    header_path = tmp_path / "header.json"
    assert run("--header", "--input", str(replay), "--output", str(header_path)) == 0
    # Paths and rule names only: the failure report must not quote players.
    assert ma_schemas.problems("header", json.loads(header_path.read_bytes())) == []

    out = tmp_path / "out"
    code = run("--frames", "--input", str(replay), "--output-dir", str(out))
    if code == UNSUPPORTED_MODE:
        return
    assert code == 0
    assert ma_schemas.problems("events", json.loads((out / "events.json").read_bytes())) == []

    schema = pl.scan_parquet(out / "frames.parquet").collect_schema()
    columns = {name: PARQUET_TYPES.get(str(kind), str(kind)) for name, kind in schema.items()}
    assert ma_schemas.frames_problems(columns) == []
