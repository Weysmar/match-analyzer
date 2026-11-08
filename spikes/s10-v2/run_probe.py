"""Spike of step 10, T10.1: the cost of subtr-actor's analysis nodes on every replay of the corpus,
next to `rl-parse --frames`. Writes `out/<sha12>/` (parser output and probe output) and
`out/cost.jsonl`. Numbers only: the probe replaces player ids by roster rows.

Usage: uv run python spikes/s10-v2/run_probe.py
"""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "games/rocket-league/parser/target/release"
PARSER = TARGET / "rl-parse"
PROBE = TARGET / "s10-probe"
REPLAYS = ROOT / "tests/fixtures/replays"
OUT = Path(__file__).resolve().parent / "out"
NODES = "touch,possession,rotation,kickoff,fifty_fifty,beaten_to_ball,rush"


def timed(command: list[str]) -> tuple[int, float, int]:
    """Exit code, wall seconds and peak memory in MB, through GNU time."""
    result = subprocess.run(
        ["/usr/bin/time", "-f", "%e %M", *command], capture_output=True, text=True
    )
    last = result.stderr.strip().splitlines()[-1].split()
    return result.returncode, float(last[0]), int(last[1]) // 1024


def main() -> int:
    OUT.mkdir(exist_ok=True)
    replays = sorted(REPLAYS.rglob("*.replay"))
    with (OUT / "cost.jsonl").open("w") as report:
        for index, replay in enumerate(replays, 1):
            digest = hashlib.sha256(replay.read_bytes()).hexdigest()[:12]
            folder = OUT / digest
            folder.mkdir(exist_ok=True)
            parse = timed(
                [str(PARSER), "--frames", "--input", str(replay), "--output-dir", str(folder)]
            )
            probe = timed([str(PROBE), "run", str(replay), str(folder / "probe.json"), NODES])
            row = {
                "replay": digest,
                "parse_code": parse[0],
                "parse_s": parse[1],
                "parse_mb": parse[2],
                "probe_code": probe[0],
                "probe_s": probe[1],
                "probe_mb": probe[2],
            }
            if probe[0] == 0:
                document = json.loads((folder / "probe.json").read_text())
                row["graph_ms"] = document["elapsed_ms"]
                row["counts"] = {name: len(items) for name, items in document["found"].items()}
            report.write(json.dumps(row) + "\n")
            print(f"{index}/{len(replays)} {digest} parse {parse[1]:.1f}s probe {probe[1]:.1f}s "
                  f"{probe[2]}MB", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
