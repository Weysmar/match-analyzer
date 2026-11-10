"""What the labels say of each V2 detector (section 4 and T12.7 of docs/PLAN-V2.md): precision over
the verdicts of `tests/fixtures/labels/`, written by the 2D view's labeling mode. Counts only.

With `--sensitivity`, also how each detector's count moves when one of its thresholds is set 20 %
lower or higher (section 4, rule 5; T14.5), over the local replays. Their parsed output is cached in
`tests/fixtures/parsed/`, never versioned, like the replays it comes from.

Usage: `python scripts/v2_report.py [--labels folder] [--sensitivity [--matches N]]`, through
`just v2-report`.
"""

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path

from rl_analysis import labels, sensitivity
from rl_analysis.match import Match, load

ROOT = Path(__file__).parents[1]
LABELS = ROOT / "tests/fixtures/labels"
REPLAYS = ROOT / "tests/fixtures/replays"
PARSED = ROOT / "tests/fixtures/parsed"
PARSER = ROOT / "games/rocket-league/parser/target/release/rl-parse"
TIMEOUT_S = 120


def parsed(replay: Path) -> Path | None:
    """The replay's parsed folder, made once: None when the parser cannot read its frames."""
    folder = PARSED / hashlib.sha256(replay.read_bytes()).hexdigest()
    if (folder / "events.json").exists():
        return folder
    if (folder / "unreadable").exists():
        return None
    folder.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [PARSER, "--frames", "--input", replay, "--output-dir", folder],
        capture_output=True,
        timeout=TIMEOUT_S,
        check=False,
    )
    if result.returncode != 0:
        (folder / "unreadable").touch()
        return None
    return folder


def corpus(limit: int) -> list[Match]:
    """Up to `limit` local matches with detected touches, in the order of their hashes."""
    if not PARSER.exists():
        sys.exit("build the parser first: cargo build --release")
    folders = [folder for replay in sorted(REPLAYS.rglob("*.replay")) if (folder := parsed(replay))]
    matches = []
    for folder in sorted(set(folders)):
        match = load(folder / "frames.parquet", folder / "events.json")
        if match.events["touches"] is not None:
            matches.append(match)
        if len(matches) == limit:
            break
    return matches


def main() -> int:
    arguments = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    arguments.add_argument("--labels", type=Path, default=LABELS)
    arguments.add_argument("--sensitivity", action="store_true")
    arguments.add_argument("--matches", type=int, default=20)
    options = arguments.parse_args()
    try:
        documents = labels.read(options.labels)
    except labels.InvalidLabelsError as error:
        print(error, file=sys.stderr)
        return 1
    print(
        labels.render(
            labels.report(documents),
            labels.tag_report(documents),
            labels.window_report(documents),
        )
    )
    if options.sensitivity:
        matches = corpus(options.matches)
        print()
        print(sensitivity.render(sensitivity.measure(matches), len(matches)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
