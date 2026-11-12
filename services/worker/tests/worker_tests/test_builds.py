"""The builds report (T9.9): a build whose matches end header-only is flagged, no other."""

from datetime import UTC, datetime, timedelta

import pytest

from ma_db.testing import Connection, Factory
from ma_worker import builds

SEEN = datetime(2026, 11, 12, tzinfo=UTC)


def line(read: int, unread: int, build: str = "260424.1") -> builds.BuildLine:
    return builds.BuildLine(build, read, unread, SEEN - timedelta(days=2), SEEN)


@pytest.mark.parametrize(
    ("read", "unread", "flagged"),
    [(0, 3, True), (3, 3, True), (4, 3, False), (0, 2, False), (100, 0, False), (0, 0, False)],
)
def test_a_build_is_flagged_from_half_header_only_over_3_matches(
    read: int, unread: int, flagged: bool
) -> None:
    assert line(read, unread).flagged(0.5, 3) is flagged


def test_the_share_counts_only_the_matches_whose_network_was_tried() -> None:
    assert line(3, 1).unread_share == 0.25
    assert line(0, 0).unread_share is None


def test_the_report_names_the_broken_build_and_what_to_do() -> None:
    text = builds.render([line(0, 5, "260501.9"), line(40, 1, "260424.1")], 0.5, 3, 30)
    assert "260501.9: 5 tried, 5 header only (100 %)" in text
    assert "260424.1: 41 tried, 1 header only (2 %)" in text
    assert text.splitlines()[-1].startswith("broken? 260501.9 ")
    assert "BROKEN?" in text.splitlines()[1]
    assert "BROKEN?" not in text.splitlines()[2]


def test_a_quiet_report() -> None:
    assert builds.render([line(10, 0)], 0.5, 3, 30).endswith("no build looks broken")
    assert builds.render([], 0.5, 3, 7) == "no match over the last 7 day(s)"


@pytest.mark.db
def test_a_fake_broken_build_is_found_in_the_database(
    conn: Connection, worker_conn: Connection, make: Factory
) -> None:
    """The end criterion of T9.9: a build whose matches all end header-only stands out, read with
    the worker's own role."""
    for status, build in [
        ("ready", "260424.1"),
        ("ready", "260424.1"),
        ("parsed", "260424.1"),
        ("header_only", "260424.1"),
        ("header_only", "999999.0"),
        ("header_only", "999999.0"),
        ("header_only", "999999.0"),
        ("failed", "999999.0"),
        ("pending", None),
    ]:
        match = make.match(status)
        conn.execute("UPDATE matches SET game_build = %s WHERE id = %s", (build, match))

    found = {line.build: line for line in builds.fetch(worker_conn, 30)}
    assert (found["999999.0"].read, found["999999.0"].unread) == (0, 3)
    assert (found["260424.1"].read, found["260424.1"].unread) == (3, 1)
    assert found["unknown"].tried == 0
    assert [name for name, line in found.items() if line.flagged(0.5, 3)] == ["999999.0"]
