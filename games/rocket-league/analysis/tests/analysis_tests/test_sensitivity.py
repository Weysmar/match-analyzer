"""Threshold sensitivity (T14.5): varying a threshold where the analysis uses it, and the report."""

from rl_analysis import commits, possession, sensitivity, thresholds
from rl_analysis.sensitivity import Row

from .test_possession import at, match


def test_a_varied_threshold_reaches_every_module_then_comes_back() -> None:
    original = thresholds.POSSESSION_WINDOW
    with sensitivity.varied("POSSESSION_WINDOW", 0.8):
        assert getattr(possession, "POSSESSION_WINDOW").value == original.value * 0.8  # noqa: B009
        assert thresholds.POSSESSION_WINDOW.value == original.value * 0.8
    assert getattr(possession, "POSSESSION_WINDOW") is original  # noqa: B009
    assert thresholds.POSSESSION_WINDOW is original
    with sensitivity.varied("DOUBLE_COMMIT_RESOLVE", 1.2):
        assert getattr(commits, "DOUBLE_COMMIT_RESOLVE").value == 1.5 * 1.2  # noqa: B009
    assert getattr(commits, "DOUBLE_COMMIT_RESOLVE").value == 1.5  # noqa: B009


def test_a_detector_moves_with_its_threshold() -> None:
    # Blue touches at 1 s and 4 s: the idle frame at 3.5 s, 2.5 s after the first touch, keeps the
    # ball blue's within 3 s but not within 2.4 s. Orange then takes it, at 4.5 s and 5 s.
    played = match(at(1.0, 0), at(4.0, 0), at(4.5, 1), at(5.0, 1))
    rows = {
        row.threshold: row for row in sensitivity.measure([played]) if row.detector == "turnover"
    }
    row = rows["POSSESSION_WINDOW"]
    assert row.base == 1
    # At 2.4 s blue never holds the ball, so orange's touches take a loose ball: no turnover.
    assert row.counts == (0, 1)
    assert row.fragile


def test_a_steady_count_is_not_fragile() -> None:
    assert not Row("overcommit", "OVERCOMMIT_MIN", 10, (12, 8)).fragile
    assert Row("overcommit", "OVERCOMMIT_MIN", 10, (16, 9)).fragile
    assert Row("overcommit", "OVERCOMMIT_MIN", 0, (0, 0)).largest_change == 0.0
    assert Row("overcommit", "OVERCOMMIT_MIN", 0, (2, 0)).fragile


def test_the_report_says_which_detectors_are_fragile() -> None:
    text = sensitivity.render(
        [
            Row("turnover", "POSSESSION_WINDOW", 10, (4, 11)),
            Row("overcommit", "OVERCOMMIT_MIN", 10, (11, 9)),
        ],
        3,
    )
    assert "over 3 match(es)" in text
    assert (
        "turnover / POSSESSION_WINDOW: 10 -> 4 (-20 %), 11 (+20 %); largest move 60 %  FRAGILE"
        in text
    )
    assert text.endswith("fragile: turnover")


def test_every_listed_threshold_exists() -> None:
    for _, names in sensitivity.DETECTORS.values():
        for name in names:
            assert isinstance(getattr(thresholds, name), thresholds.Threshold), name
