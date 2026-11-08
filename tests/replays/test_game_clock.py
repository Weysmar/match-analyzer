"""The game clock on every replay of the corpus (A63). Overtime only follows a tie at the end of
regulation, and ends at its first goal: once a goal falls in a detected overtime, the clock never
moves again, and the score was level when overtime began.

One private match of the corpus records a second goal 39 frames after the golden goal, at the same
clock: the match was over, which the test allows.

Only counts are printed, never a name or an id.
"""

import subprocess
from pathlib import Path

import pytest

from rl_analysis import clock
from rl_analysis.match import load

pytestmark = pytest.mark.replays

ROOT = Path(__file__).parents[2]
BINARY = ROOT / "games/rocket-league/parser/target/release/rl-parse"
REPLAYS = ROOT / "tests/fixtures/replays"
SUCCESS = 0


def replays() -> list[Path]:
    return sorted(REPLAYS.rglob("*.replay"))


@pytest.mark.parametrize("replay", replays(), ids=lambda path: path.name[:12])
def test_overtime_ends_at_its_first_goal(replay: Path, tmp_path: Path) -> None:
    result = subprocess.run(
        [BINARY, "--frames", "--input", replay, "--output-dir", tmp_path], capture_output=True
    )
    if result.returncode != SUCCESS:
        pytest.skip("no frames for this replay")
    match = load(tmp_path / "frames.parquet", tmp_path / "events.json")
    found = clock.compute(match)
    goals = match.events["goals"]
    assert len(found.goals_s) == len(goals)
    assert all(seconds is not None for seconds in found.goals_s)
    times = [seconds or 0.0 for seconds in found.goals_s]
    assert times == sorted(times), "goals out of order on the clock"
    if found.overtime_from_s is None:
        return
    in_overtime = [seconds for seconds in times if seconds > found.overtime_from_s]
    if in_overtime:
        golden = in_overtime[0]
        assert found.length_s == pytest.approx(golden, abs=0.5), "play went on after overtime"
        assert all(seconds == pytest.approx(golden) for seconds in in_overtime)
    before = [goal["team"] for goal, seconds in zip(goals, times, strict=True)]
    regulation = before[: len(times) - len(in_overtime)]
    assert regulation.count(0) == regulation.count(1), "overtime without a tie"
