"""Reading the labeling mode's verdicts, and the precision they give each detector (T12.7)."""

import json
from pathlib import Path
from typing import Any

import pytest

from rl_analysis import labels

MATCH = "731bfcac-3c1f-5aa8-9259-226a1098ea5c"


def document(
    verdicts: list[str], *, labeled_at: str = "2026-11-10T20:00:00Z", match: str = MATCH
) -> dict[str, Any]:
    return {
        "version": 1,
        "match_id": match,
        "detector": "turnover",
        "labeled_at": labeled_at,
        "labels": [
            {"time_s": 10.0 + index, "clock_s": 5.0 + index, "verdict": verdict}
            for index, verdict in enumerate(verdicts)
        ],
    }


def test_precision_leaves_the_uncertain_out() -> None:
    [line] = labels.report([document(["true"] * 6 + ["false"] * 2 + ["uncertain"] * 2)])
    assert (line.true, line.false, line.uncertain, line.judged) == (6, 2, 2, 8)
    assert line.precision == pytest.approx(0.75)


def test_too_few_verdicts_are_said_so() -> None:
    [line] = labels.report([document(["true"] * 10)])
    assert line.status == "too_few"


@pytest.mark.parametrize(("true", "status"), [(48, "on_target"), (47, "below_target")])
def test_the_target_is_80_percent_over_60_verdicts(true: int, status: str) -> None:
    [line] = labels.report([document(["true"] * true + ["false"] * (60 - true))])
    assert line.status == status


def test_a_situation_labeled_twice_keeps_its_latest_verdict() -> None:
    first = document(["false"], labeled_at="2026-11-10T20:00:00Z")
    again = document(["true"], labeled_at="2026-11-11T08:00:00Z")
    [line] = labels.report([again, first])
    assert (line.true, line.false, line.files) == (1, 0, 2)


def test_matches_add_up() -> None:
    other = "00000000-0000-4000-8000-000000000001"
    [line] = labels.report([document(["true"]), document(["false"], match=other)])
    assert line.judged == 2


def test_files_are_read_and_checked(tmp_path: Path) -> None:
    (tmp_path / "a-turnover.json").write_text(json.dumps(document(["true"])), encoding="utf-8")
    assert len(labels.read(tmp_path)) == 1
    broken = document(["maybe"])
    (tmp_path / "b-turnover.json").write_text(json.dumps(broken), encoding="utf-8")
    with pytest.raises(labels.InvalidLabelsError, match=r"b-turnover.json"):
        labels.read(tmp_path)


def test_no_folder_is_no_label(tmp_path: Path) -> None:
    assert labels.read(tmp_path / "missing") == []
    assert "no label yet" in labels.render([])


def test_the_report_holds_counts_only() -> None:
    text = labels.render(labels.report([document(["true", "false", "uncertain"])]))
    assert text.startswith(
        "turnover: 2 judged (1 true, 1 false), 1 uncertain, 1 file(s); precision 50 %"
    )
    assert MATCH not in text
