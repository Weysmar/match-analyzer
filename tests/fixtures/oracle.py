"""subtr-actor's statistics for each replay of the corpus, cached. `rl-oracle` takes 13 minutes on
the whole corpus, and up to two on a long replay, for an output that never changes for a file.

Usage: `python tests/fixtures/oracle.py build`, through `just oracle-cache`. The cache sits next to
the replays, never versioned either: it is derived from them. Its folder names the subtr-actor
version and rl-oracle's output format, so that a new version of either starts afresh.
"""

import hashlib
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).parents[2]
REPLAYS = ROOT / "tests/fixtures/replays"
BINARY = ROOT / "games/rocket-league/parser/target/release/rl-oracle"
SUBTR_ACTOR = "1.5.1"
# What rl-oracle writes: a new field means a new cache, as a new subtr-actor does.
# 2: touches, team and player possession (T11.7 of docs/PLAN-V2.md).
OUTPUT_FORMAT = 2
CACHE = ROOT / f"tests/fixtures/oracle/subtr-actor-{SUBTR_ACTOR}-format-{OUTPUT_FORMAT}"
TIMEOUT_S = 600
UNREADABLE = b"null\n"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cache_path(replay: Path) -> Path:
    return CACHE / f"{sha256(replay)}.json"


def read(replay: Path) -> bytes | None:
    """The cached output: `null` when subtr-actor could not read the replay, None if not cached."""
    path = cache_path(replay)
    return path.read_bytes() if path.exists() else None


def _build_one(replay: Path) -> bool:
    target = cache_path(replay)
    if target.exists():
        return False
    result = subprocess.run([BINARY, replay], capture_output=True, timeout=TIMEOUT_S, check=False)
    target.write_bytes(result.stdout if result.returncode == 0 else UNREADABLE)
    return True


def build() -> int:
    CACHE.mkdir(parents=True, exist_ok=True)
    replays = sorted(REPLAYS.rglob("*.replay"))
    with ThreadPoolExecutor(os.cpu_count() or 2) as pool:
        built = sum(pool.map(_build_one, replays))
    print(f"oracle cache: {len(replays)} replays, {built} computed now")
    return 0


if __name__ == "__main__":
    if sys.argv[1:] != ["build"]:
        sys.exit("usage: oracle.py build")
    sys.exit(build())
