"""Every threshold says where it comes from (section 4 of docs/PLAN-V2.md)."""

import pytest

from rl_analysis import thresholds
from rl_analysis.thresholds import SOURCES, Threshold

DECLARED = {
    name: value for name, value in vars(thresholds).items() if name.isupper() and name != "SOURCES"
}


def test_there_are_thresholds_to_check() -> None:
    assert DECLARED


@pytest.mark.parametrize("name", sorted(DECLARED))
def test_a_threshold_is_a_threshold(name: str) -> None:
    """A bare number would carry no unit and no source."""
    assert isinstance(DECLARED[name], Threshold), name


@pytest.mark.parametrize("name", sorted(DECLARED))
def test_a_threshold_names_its_source(name: str) -> None:
    threshold = DECLARED[name]
    assert threshold.source.split(" ", 1)[0] in SOURCES, name
    # More than the kind: which measure, which constant of subtr-actor, or why a convention.
    assert len(threshold.source.split()) >= 3, name
    assert threshold.unit, name


def test_a_number_without_source_is_refused() -> None:
    assert Threshold(1.0, "s", "a hunch").source.split(" ", 1)[0] not in SOURCES
