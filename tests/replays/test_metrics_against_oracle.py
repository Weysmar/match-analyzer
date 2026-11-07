"""The real-replay check of each metric (section 8.2 of CLAUDE.md): rl_analysis on the frames that
`rl-parse` writes, against subtr-actor's own statistics through `rl-oracle`.

Only counts and differences are printed, never a name or an id.
"""

import hashlib
import json
import statistics
import subprocess
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from rl_analysis.frames import read
from rl_analysis.registry import compute

pytestmark = pytest.mark.replays

ROOT = Path(__file__).parents[2]
RELEASE = ROOT / "games/rocket-league/parser/target/release"
REPLAYS = ROOT / "tests/fixtures/replays"
UNSUPPORTED_MODE = 14
RAW_TO_PERCENT = 100.0 / 255.0
# Written by `just oracle-cache` (tests/fixtures/oracle.py), keyed by the replay's hash.
ORACLE_CACHE = ROOT / "tests/fixtures/oracle/subtr-actor-1.5.1"


def cached_oracle(replay: Path) -> Any:
    """subtr-actor's statistics for this replay: None when it could not read the replay."""
    path = ORACLE_CACHE / f"{hashlib.sha256(replay.read_bytes()).hexdigest()}.json"
    assert path.exists(), "run `just oracle-cache`"
    return json.loads(path.read_bytes())


def share(oracle: dict[str, Any], module: str, field: str, scale: float) -> float | None:
    """`field` over the module's tracked time, scaled. None when subtr-actor tracked nothing."""
    stats = oracle.get(module)
    if not isinstance(stats, dict) or not stats.get("tracked_time"):
        return None
    return scale * float(stats[field]) / float(stats["tracked_time"])


# What subtr-actor says for each metric, in our units. Its boost is raw, from 0 to 255.
THEIRS: dict[str, Callable[[dict[str, Any]], float | None]] = {
    "boost.avg": lambda o: share(o, "boost", "boost_integral", RAW_TO_PERCENT),
    "boost.pct_zero": lambda o: share(o, "boost", "time_zero_boost", 100.0),
    "boost.pct_full": lambda o: share(o, "boost", "time_hundred_boost", 100.0),
}

# Measured by the spike (section 7 of its report) on 277 players: median and 95th percentile of the
# absolute difference. The bounds leave a margin on top of them.
#
# Like the spike, the comparison keeps the current replay format (`net` 10 or more): 5 replays of
# the corpus are older. On two of them, from 2016, subtr-actor's boost module tracks a player 30 to
# 69 s less than its own movement and positioning modules do, which both match our reference time
# exactly: the reference is off there, not the metric. Players upload the current format.
CURRENT_FORMAT_NET = 10
BOUNDS = {
    "boost.avg": (0.02, 0.1),
    "boost.pct_zero": (0.3, 1.5),
    "boost.pct_full": (0.3, 0.5),
}


@dataclass
class Corpus:
    differences: dict[str, list[float]]
    replays: int
    skipped: int
    old_format: int
    teams_mismatched: int


def distinct_replays() -> list[Path]:
    seen: dict[bytes, Path] = {}
    for path in sorted(REPLAYS.rglob("*.replay")):
        seen.setdefault(path.read_bytes()[:4096] + str(path.stat().st_size).encode(), path)
    return list(seen.values())


@pytest.fixture(scope="module")
def corpus(tmp_path_factory: pytest.TempPathFactory) -> Corpus:
    differences: dict[str, list[float]] = defaultdict(list)
    replays = skipped = old_format = mismatched = 0
    for replay in distinct_replays():
        folder = tmp_path_factory.mktemp("frames")
        parsed = subprocess.run(
            [RELEASE / "rl-parse", "--frames", "--input", replay, "--output-dir", folder],
            capture_output=True,
        )
        if parsed.returncode == UNSUPPORTED_MODE:
            continue
        assert parsed.returncode == 0
        header_path = folder / "header.json"
        subprocess.run(
            [RELEASE / "rl-parse", "--header", "--input", replay, "--output", header_path],
            check=True,
            capture_output=True,
        )
        net = json.loads(header_path.read_text(encoding="utf-8"))["replay_version"]["net"]
        if net is None or net < CURRENT_FORMAT_NET:
            old_format += 1
            continue
        oracle = cached_oracle(replay)
        if oracle is None:
            skipped += 1
            continue
        replays += 1
        theirs = {row["player_idx"]: row for row in oracle["players"]}
        roster = json.loads((folder / "events.json").read_text(encoding="utf-8"))["roster"]
        mismatched += sum(
            theirs[member["player_idx"]]["team"] != member["team"] for member in roster
        )
        for player, values in compute(read(folder / "frames.parquet")).items():
            for metric_id, mine in values.items():
                expected = THEIRS[metric_id](theirs[player])
                if mine is not None and expected is not None:
                    differences[metric_id].append(abs(mine - expected))
    return Corpus(differences, replays, skipped, old_format, mismatched)


def test_the_oracle_lines_up_with_the_roster(corpus: Corpus) -> None:
    """Same players in the same order: otherwise every comparison below would be meaningless."""
    assert corpus.replays > 0
    assert corpus.teams_mismatched == 0


@pytest.mark.parametrize("metric_id", sorted(BOUNDS))
def test_a_metric_agrees_with_subtr_actor(
    corpus: Corpus, metric_id: str, capsys: pytest.CaptureFixture[str]
) -> None:
    found = sorted(corpus.differences[metric_id])
    assert found
    median = statistics.median(found)
    p95 = found[int(0.95 * (len(found) - 1))]
    with capsys.disabled():
        print(
            f"\n{metric_id}: {len(found)} players in {corpus.replays} replays "
            f"({corpus.skipped} unread by subtr-actor, {corpus.old_format} of an old format "
            f"left out), |diff| median {median:.4f}, "
            f"p95 {p95:.4f}, max {found[-1]:.4f}"
        )
    median_bound, p95_bound = BOUNDS[metric_id]
    assert median <= median_bound
    assert p95 <= p95_bound
