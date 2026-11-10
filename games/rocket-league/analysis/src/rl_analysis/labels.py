"""Verdicts from the 2D view's labeling mode (T12.7, T15.4 and T17.1 of docs/PLAN-V2.md), and what
they say of each detection.

The labeling mode writes its files into `tests/fixtures/labels/`
(`packages/schemas/labels.schema.json`, never versioned), of three kinds:

- verdicts on the detections of one detector: its **precision**, against 80 % over 60 verdicts;
- a blind review of the goals conceded, each tag judged there or not without seeing what was
  detected: each tag's **precision** and **recall**, over 30 goals (T15.4);
- windows of 10 s of play, before goals and at random, each detector judged there or not without
  the detections on the cursor: each detector's **recall**, against 60 % over 30 windows (T17.1).

Uncertain verdicts stay out of every measure (section 4, rule 4). A thing labeled twice counts once,
with its latest verdict.
"""

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ma_schemas import problems

PRECISION_TARGET = 0.80
RECALL_TARGET = 0.60
ENOUGH = 60
# T15.4 reviews 30 goals; T17.1 judges 30 windows per detector.
ENOUGH_GOALS = 30
ENOUGH_WINDOWS = 30


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
        if "kind" in document:
            continue
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


def render(
    lines: list[DetectorReport],
    tags: list[TagReport] | None = None,
    windows: list[WindowReport] | None = None,
) -> str:
    """The report as text: counts and percentages only."""
    if not lines and not tags and not windows:
        return "no label yet: label situations in the 2D view (development only), then run again"
    out = []
    for line in lines:
        precision = "n/a" if line.precision is None else f"{100 * line.precision:.0f} %"
        out.append(
            f"{line.detector}: {line.judged} judged ({line.true} true, {line.false} false), "
            f"{line.uncertain} uncertain, {line.files} file(s); precision {precision}; "
            f"{line.status} (target {100 * PRECISION_TARGET:.0f} % over {ENOUGH} verdicts)"
        )
    if tags:
        out.append(
            f"goals conceded, blind review (targets: precision {_pct(PRECISION_TARGET)}, "
            f"recall {_pct(RECALL_TARGET)}, over {ENOUGH_GOALS} goals):"
        )
        out += [
            f"  {tag.tag}: {tag.judged} goal(s) judged, {tag.uncertain} uncertain; "
            f"precision {_pct(tag.precision)} "
            f"({tag.true_positive}/{tag.true_positive + tag.false_positive}), "
            f"recall {_pct(tag.recall)} "
            f"({tag.true_positive}/{tag.true_positive + tag.false_negative}); {tag.status}"
            for tag in tags
        ]
    if windows:
        out.append(
            f"windows of play (target: recall {_pct(RECALL_TARGET)} over {ENOUGH_WINDOWS} windows):"
        )
        out += [
            f"  {window.detector}: {window.judged} window(s) judged, {window.uncertain} uncertain; "
            f"there in {window.present}, detected in {window.found} of them: recall "
            f"{_pct(window.recall)}; detected while absent: {window.spurious}; {window.status}"
            for window in windows
        ]
    return "\n".join(out)


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{100 * value:.0f} %"


def _latest(
    documents: list[dict[str, object]], kind: str, items: str, key: str
) -> list[dict[str, Any]]:
    """The items of every file of this kind, the latest of each, named by match and `key`."""
    found: dict[tuple[str, float], tuple[str, dict[str, Any]]] = {}
    for document in documents:
        if document.get("kind") != kind:
            continue
        match, labeled_at = str(document["match_id"]), str(document["labeled_at"])
        entries = document[items]
        assert isinstance(entries, list)
        for entry in entries:
            name = (match, round(float(entry[key]), 1))
            if name not in found or found[name][0] <= labeled_at:
                found[name] = (labeled_at, entry)
    return [entry for _, entry in found.values()]


@dataclass(frozen=True)
class TagReport:
    """One tag of a goal conceded over the goals reviewed blind: detected or not, there or not."""

    tag: str
    true_positive: int
    false_positive: int
    false_negative: int
    true_negative: int
    uncertain: int

    @property
    def judged(self) -> int:
        return self.true_positive + self.false_positive + self.false_negative + self.true_negative

    @property
    def precision(self) -> float | None:
        detected = self.true_positive + self.false_positive
        return self.true_positive / detected if detected else None

    @property
    def recall(self) -> float | None:
        there = self.true_positive + self.false_negative
        return self.true_positive / there if there else None

    @property
    def status(self) -> str:
        if self.judged < ENOUGH_GOALS:
            return "too_few"
        precise = self.precision is None or self.precision >= PRECISION_TARGET
        complete = self.recall is None or self.recall >= RECALL_TARGET
        return "on_target" if precise and complete else "below_target"


def tag_report(documents: list[dict[str, object]]) -> list[TagReport]:
    """One line per tag judged at least once, in name order."""
    counts: dict[str, Counter[str]] = {}
    for goal in _latest(documents, "goals", "goals", "time_s"):
        detected = set(goal["detected"])
        for tag, verdict in goal["verdicts"].items():
            count = counts.setdefault(tag, Counter())
            if verdict == "uncertain":
                count["uncertain"] += 1
            elif verdict == "true":
                count["tp" if tag in detected else "fn"] += 1
            else:
                count["fp" if tag in detected else "tn"] += 1
    return [
        TagReport(tag, c["tp"], c["fp"], c["fn"], c["tn"], c["uncertain"])
        for tag, c in sorted(counts.items())
    ]


@dataclass(frozen=True)
class WindowReport:
    """One detector over the windows of play judged: there or not, detected or not."""

    detector: str
    present: int
    found: int
    absent: int
    spurious: int
    uncertain: int

    @property
    def judged(self) -> int:
        return self.present + self.absent

    @property
    def recall(self) -> float | None:
        return self.found / self.present if self.present else None

    @property
    def status(self) -> str:
        if self.judged < ENOUGH_WINDOWS:
            return "too_few"
        return (
            "on_target" if self.recall is None or self.recall >= RECALL_TARGET else "below_target"
        )


def window_report(documents: list[dict[str, object]]) -> list[WindowReport]:
    """One line per detector judged at least once, in name order."""
    counts: dict[str, Counter[str]] = {}
    for window in _latest(documents, "windows", "windows", "start_clock_s"):
        for detector, verdict in window["verdicts"].items():
            detected = bool(window["detected"].get(detector, False))
            count = counts.setdefault(detector, Counter())
            if verdict == "uncertain":
                count["uncertain"] += 1
            elif verdict == "true":
                count["present"] += 1
                count["found"] += detected
            else:
                count["absent"] += 1
                count["spurious"] += detected
    return [
        WindowReport(d, c["present"], c["found"], c["absent"], c["spurious"], c["uncertain"])
        for d, c in sorted(counts.items())
    ]
