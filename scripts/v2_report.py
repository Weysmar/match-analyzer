"""What the labels say of each V2 detector (section 4 and T12.7 of docs/PLAN-V2.md): precision over
the verdicts of `tests/fixtures/labels/`, written by the 2D view's labeling mode. Counts only.

Usage: `python scripts/v2_report.py [folder]`, through `just v2-report`. The sensitivity of each
count to its thresholds (rule 5) comes with the calibration of step 17.
"""

import sys
from pathlib import Path

from rl_analysis import labels

FOLDER = Path(__file__).parents[1] / "tests/fixtures/labels"


def main() -> int:
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else FOLDER
    try:
        documents = labels.read(folder)
    except labels.InvalidLabelsError as error:
        print(error, file=sys.stderr)
        return 1
    print(labels.render(labels.report(documents)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
