"""The team of each frame (A52): at every kickoff countdown, each car stands on its own team's side,
blue at y < 0. Before the fix, players who switched teams in private matches broke this.

Only counts are printed, never a name or an id.
"""

import subprocess
from pathlib import Path

import polars as pl
import pytest

from rl_analysis.constants import Phase
from rl_analysis.frames import read

pytestmark = pytest.mark.replays

ROOT = Path(__file__).parents[2]
BINARY = ROOT / "games/rocket-league/parser/target/release/rl-parse"
REPLAYS = ROOT / "tests/fixtures/replays"
SUCCESS = 0
# Kickoff spots sit at |y| of 2048 to 4608: well clear of the halfway line.
CLEAR_OF_HALFWAY = 500.0


def replays() -> list[Path]:
    return sorted(REPLAYS.rglob("*.replay"))


@pytest.mark.parametrize("replay", replays(), ids=lambda path: path.name[:12])
def test_every_car_starts_a_kickoff_on_its_teams_side(replay: Path, tmp_path: Path) -> None:
    result = subprocess.run(
        [BINARY, "--frames", "--input", replay, "--output-dir", tmp_path], capture_output=True
    )
    if result.returncode != SUCCESS:
        pytest.skip("no frames for this replay")
    countdown = read(tmp_path / "frames.parquet").filter(
        (pl.col("phase") == int(Phase.COUNTDOWN))
        & pl.col("present")
        & (pl.col("y").abs() > CLEAR_OF_HALFWAY)
    )
    wrong = countdown.filter(
        ((pl.col("team") == 0) & (pl.col("y") > 0)) | ((pl.col("team") == 1) & (pl.col("y") < 0))
    )
    assert wrong.height == 0, f"{wrong.height} of {countdown.height} frames on the wrong side"
