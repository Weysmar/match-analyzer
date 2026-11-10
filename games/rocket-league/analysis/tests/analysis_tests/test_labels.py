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


def goals(
    *reviewed: tuple[list[str], dict[str, str]], labeled_at: str = "2026-11-10T20:00:00Z"
) -> dict[str, Any]:
    """A blind review of goals: for each, the tags detected and the verdicts given."""
    return {
        "version": 1,
        "match_id": MATCH,
        "kind": "goals",
        "labeled_at": labeled_at,
        "goals": [
            {
                "time_s": 30.0 + 10 * index,
                "clock_s": 20.0 + 10 * index,
                "detected": detected,
                "verdicts": verdicts,
            }
            for index, (detected, verdicts) in enumerate(reviewed)
        ],
    }


def test_each_tag_has_its_precision_and_recall_worked_out_by_hand() -> None:
    """Four goals. double_commit: detected and there (TP), detected but not there (FP), there but
    missed (FN), neither (TN): precision 1/2, recall 1/2. last_back_far: only uncertain."""
    document = goals(
        (["double_commit"], {"double_commit": "true", "last_back_far": "uncertain"}),
        (["double_commit"], {"double_commit": "false"}),
        ([], {"double_commit": "true"}),
        ([], {"double_commit": "false"}),
    )
    double, far = labels.tag_report([document])
    assert (double.tag, double.true_positive, double.false_positive) == ("double_commit", 1, 1)
    assert (double.false_negative, double.true_negative, double.judged) == (1, 1, 4)
    assert (double.precision, double.recall, double.status) == (0.5, 0.5, "too_few")
    assert (far.tag, far.judged, far.uncertain, far.precision, far.recall) == (
        "last_back_far",
        0,
        1,
        None,
        None,
    )


def test_a_tag_on_target_over_30_goals() -> None:
    reviewed = [(["overcommit"], {"overcommit": "true"})] * 25 + [([], {"overcommit": "false"})] * 5
    [line] = labels.tag_report([goals(*reviewed)])
    assert (line.precision, line.recall, line.status) == (1.0, 1.0, "on_target")


def test_a_goal_reviewed_twice_keeps_its_latest_verdicts() -> None:
    first = goals(
        (["double_commit"], {"double_commit": "false"}), labeled_at="2026-11-10T20:00:00Z"
    )
    second = goals(
        (["double_commit"], {"double_commit": "true"}), labeled_at="2026-11-10T21:00:00Z"
    )
    [line] = labels.tag_report([second, first])
    assert (line.true_positive, line.false_positive) == (1, 0)


def windows(*judged: tuple[dict[str, bool], dict[str, str]]) -> dict[str, Any]:
    return {
        "version": 1,
        "match_id": MATCH,
        "kind": "windows",
        "labeled_at": "2026-11-10T20:00:00Z",
        "windows": [
            {
                "start_clock_s": 10.0 * index,
                "end_clock_s": 10.0 * index + 10.0,
                "source": "random",
                "detected": detected,
                "verdicts": verdicts,
            }
            for index, (detected, verdicts) in enumerate(judged)
        ],
    }


def test_each_detector_has_its_recall_over_the_windows_worked_out_by_hand() -> None:
    """Turnovers there in 3 windows, detected in 2 (recall 2/3); detected once where absent."""
    document = windows(
        ({"turnover": True}, {"turnover": "true", "overcommit": "false"}),
        ({"turnover": True}, {"turnover": "true"}),
        ({"turnover": False}, {"turnover": "true", "overcommit": "uncertain"}),
        ({"turnover": True}, {"turnover": "false"}),
        ({"turnover": False}, {"turnover": "false"}),
    )
    overcommit, turnover = labels.window_report([document])
    assert (turnover.present, turnover.found, turnover.absent, turnover.spurious) == (3, 2, 2, 1)
    assert turnover.recall == pytest.approx(2 / 3)
    assert (overcommit.judged, overcommit.uncertain, overcommit.recall) == (1, 1, None)


def test_the_three_kinds_of_file_follow_the_schema(tmp_path: Path) -> None:
    for name, content in (
        ("a-turnover.json", document(["true"])),
        ("a-goals.json", goals((["kickoff_goal"], {"kickoff_goal": "true"}))),
        ("a-windows.json", windows(({"overcommit": False}, {"overcommit": "false"}))),
    ):
        (tmp_path / name).write_text(json.dumps(content), encoding="utf-8")
    read = labels.read(tmp_path)
    assert len(read) == 3
    assert len(labels.report(read)) == 1
    bad = goals((["made_up"], {"made_up": "true"}))
    (tmp_path / "bad.json").write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(labels.InvalidLabelsError):
        labels.read(tmp_path)


def test_the_full_report_holds_counts_only() -> None:
    text = labels.render(
        [],
        labels.tag_report([goals((["double_commit"], {"double_commit": "true"}))]),
        labels.window_report([windows(({"turnover": False}, {"turnover": "true"}))]),
    )
    assert "double_commit: 1 goal(s) judged" in text
    assert "turnover: 1 window(s) judged" in text
    assert "recall 0 %" in text
