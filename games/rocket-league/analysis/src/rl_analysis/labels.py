"""Verdicts on detected situations (T12.7 of docs/PLAN-V2.md), and what they say of each detector.

The 2D view's labeling mode writes one file per match and detector into `tests/fixtures/labels/`
(`packages/schemas/labels.schema.json`, never versioned). `just v2-report` reads them all: for each
detector, its precision over the verdicts that are not uncertain, against the target of section 4
(80 %), and whether there are enough verdicts yet to judge (60 at step 17).
"""

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from ma_schemas import problems

PRECISION_TARGET = 0.80
ENOUGH = 60


@dataclass(frozen=True)
class DetectorReport:
    detector: str
    files: int
    true: int
    false: int
    uncertain: int

    @property
    def judged(self) -> int:
        """Verdicts that count: the uncertain ones stay out."""
        return self.true + self.false

    @property
    def precision(self) -> float | None:
        return self.true / self.judged if self.judged else None

    @property
    def status(self) -> str:
        if self.judged < ENOUGH:
            return "too_few"
        assert self.precision is not None
        return "on_target" if self.precision >= PRECISION_TARGET else "below_target"


class InvalidLabelsError(ValueError):
    """A label file off its schema. The message names the file and paths, never values."""


def read(folder: Path) -> list[dict[str, object]]:
    """Every label file of the folder, checked. A folder that is not there holds none."""
    documents = []
    for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        document = json.loads(path.read_text(encoding="utf-8"))
        found = problems("labels", document)
        if found:
            raise InvalidLabelsError(f"{path.name}: " + "; ".join(found[:5]))
        documents.append(document)
    return documents


def report(documents: list[dict[str, object]]) -> list[DetectorReport]:
    """One line per detector, in name order. A situation labeled twice, in two files of the same
    match, counts once, with its latest verdict."""
    latest: dict[tuple[str, str, float], tuple[str, str]] = {}
    files: Counter[str] = Counter()
    for document in documents:
        detector, match = str(document["detector"]), str(document["match_id"])
        files[detector] += 1
        labeled_at = str(document["labeled_at"])
        labels = document["labels"]
        assert isinstance(labels, list)
        for label in labels:
            key = (detector, match, round(float(label["time_s"]), 3))
            if key not in latest or latest[key][0] <= labeled_at:
                latest[key] = (labeled_at, str(label["verdict"]))
    verdicts: dict[str, Counter[str]] = {}
    for (detector, _, _), (_, verdict) in latest.items():
        verdicts.setdefault(detector, Counter())[verdict] += 1
    return [
        DetectorReport(
            detector=detector,
            files=files[detector],
            true=verdicts.get(detector, Counter())["true"],
            false=verdicts.get(detector, Counter())["false"],
            uncertain=verdicts.get(detector, Counter())["uncertain"],
        )
        for detector in sorted(files)
    ]


def render(lines: list[DetectorReport]) -> str:
    """The report as text: counts and percentages only."""
    if not lines:
        return "no label yet: label situations in the 2D view (development only), then run again"
    out = []
    for line in lines:
        precision = "n/a" if line.precision is None else f"{100 * line.precision:.0f} %"
        out.append(
            f"{line.detector}: {line.judged} judged ({line.true} true, {line.false} false), "
            f"{line.uncertain} uncertain, {line.files} file(s); precision {precision}; "
            f"{line.status} (target {100 * PRECISION_TARGET:.0f} % over {ENOUGH} verdicts)"
        )
    return "\n".join(out)
