"""Spike of step 10, T10.1: summary of `out/cost.jsonl`. Numbers only.

Usage: uv run python spikes/s10-v2/summarize_cost.py
"""

import json
import statistics
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent / "out"


def main() -> int:
    rows = [json.loads(line) for line in (OUT / "cost.jsonl").read_text().splitlines()]
    ok = [r for r in rows if r["probe_code"] == 0 and r["parse_code"] == 0]
    failed_probe = [r for r in rows if r["probe_code"] != 0 and r["parse_code"] == 0]
    print(f"replays {len(rows)}, both ran {len(ok)}, probe failed where the parser did not "
          f"{len(failed_probe)}, parser failed {sum(r['parse_code'] != 0 for r in rows)}")
    for key in ("parse_s", "probe_s", "graph_ms", "parse_mb", "probe_mb"):
        values = [r[key] for r in ok]
        print(f"{key:9} median {statistics.median(values):8.2f}  max {max(values):8.2f}")
    ratio = [r["probe_s"] / r["parse_s"] for r in ok if r["parse_s"] > 0]
    print(f"probe / parse time: median {statistics.median(ratio):.1f}x, max {max(ratio):.1f}x")
    for name in ("touches", "possession", "rotation_roles", "kickoffs", "fifty_fifty",
                 "beaten_to_ball", "rush"):
        values = [r["counts"].get(name, 0) for r in ok]
        print(f"{name:15} per replay: median {statistics.median(values):6.0f}  max {max(values):6}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
