"""Whether the production limits let the real parser through (T6.3): `RLIMIT_AS` counts virtual
memory, so the 512 MB measured against resident memory had to be checked here."""

from pathlib import Path

import pytest

from ma_worker.sandbox import Limits, run

pytestmark = pytest.mark.replays

ROOT = Path(__file__).parents[2]
BINARY = ROOT / "games/rocket-league/parser/target/release/rl-parse"
REPLAYS = ROOT / "tests/fixtures/replays"
SUCCESS = 0
UNSUPPORTED_MODE = 14
# The defaults of `.env.example`.
LIMITS = Limits(timeout_s=30, memory_mb=512)


def replays() -> list[Path]:
    return sorted(REPLAYS.rglob("*.replay"))


@pytest.mark.parametrize("replay", replays(), ids=lambda path: path.name[:12])
def test_the_limits_let_a_real_replay_through(replay: Path, tmp_path: Path) -> None:
    (tmp_path / "input.replay").write_bytes(replay.read_bytes())
    (tmp_path / "out").mkdir()
    header = run(
        BINARY, ["--header", "--input", "input.replay", "--output", "header.json"], tmp_path, LIMITS
    )
    assert header.exit_code == SUCCESS
    frames = run(
        BINARY, ["--frames", "--input", "input.replay", "--output-dir", "out"], tmp_path, LIMITS
    )
    assert frames.timed_out is False
    assert frames.exit_code in (SUCCESS, UNSUPPORTED_MODE)
