"""Loading, reference time and the field as each team sees it."""

from pathlib import Path

import polars as pl
import pytest

from rl_analysis.constants import Phase
from rl_analysis.frames import (
    InvalidFramesError,
    check,
    in_live_play,
    in_motion,
    read,
    relative_y,
    time_average,
    time_share,
)

from .synthetic import frames, row


def test_a_file_with_the_schemas_columns_loads(tmp_path: Path) -> None:
    path = tmp_path / "frames.parquet"
    frames(row()).write_parquet(path)
    assert read(path).height == 1


@pytest.mark.parametrize(
    "change",
    [
        lambda f: f.drop("boost"),
        lambda f: f.with_columns(pl.lit(1).alias("extra")),
        lambda f: f.with_columns(pl.col("boost").cast(pl.Float64)),
        lambda f: f.select(reversed(f.columns)),
    ],
)
def test_a_file_off_the_schema_is_refused(change: object) -> None:
    with pytest.raises(InvalidFramesError):
        check(change(frames(row())))  # type: ignore[operator]


def test_the_error_names_columns_not_values() -> None:
    with pytest.raises(InvalidFramesError) as error:
        check(frames(row()).drop("boost"))
    assert "boost" in str(error.value)


@pytest.mark.parametrize(
    ("phase", "motion", "live"),
    [
        (Phase.UNKNOWN, False, False),
        (Phase.COUNTDOWN, False, False),
        (Phase.KICKOFF_WAITING, True, False),
        (Phase.ACTIVE, True, True),
        (Phase.AFTER_GOAL, False, False),
    ],
)
def test_reference_time_by_phase(phase: Phase, motion: bool, live: bool) -> None:
    frame = frames(row(phase=int(phase)))
    assert frame.select(in_motion()).item() is motion
    assert frame.select(in_live_play()).item() is live


@pytest.mark.parametrize("fields", [{"present": False}, {"demolished": True}])
def test_an_absent_or_demolished_car_is_never_counted(fields: dict[str, bool]) -> None:
    frame = frames(row(**fields))
    assert frame.select(in_motion()).item() is False
    assert frame.select(in_live_play()).item() is False


def test_orange_sees_the_field_mirrored() -> None:
    frame = frames(row(team=0, y=1000.0), row(team=1, y=1000.0, player_idx=1))
    assert frame.select(relative_y("y")).to_series().to_list() == [1000.0, -1000.0]


def test_an_average_weighs_frames_by_their_time() -> None:
    """Two frames: 10 for 3 s, 40 for 1 s. Counting frames would say 25."""
    frame = frames(row(boost=10.0, dt_s=3.0), row(boost=40.0, dt_s=1.0))
    assert time_average(frame, in_motion(), pl.col("boost")) == {0: pytest.approx(17.5)}


def test_an_unknown_value_is_left_out_of_an_average() -> None:
    frame = frames(row(boost=10.0, dt_s=1.0), row(boost=None, dt_s=5.0))
    assert time_average(frame, in_motion(), pl.col("boost")) == {0: pytest.approx(10.0)}


def test_a_share_weighs_frames_by_their_time() -> None:
    frame = frames(row(boost=0.0, dt_s=1.0), row(boost=50.0, dt_s=3.0))
    assert time_share(frame, in_motion(), pl.col("boost") == 0.0) == {0: pytest.approx(25.0)}


def test_a_player_with_no_reference_time_has_no_value() -> None:
    frame = frames(row(phase=int(Phase.COUNTDOWN)), row(player_idx=1, team=1))
    assert time_average(frame, in_motion(), pl.col("boost")) == {0: None, 1: pytest.approx(50.0)}
    assert time_share(frame, in_motion(), pl.col("boost") > 0) == {0: None, 1: pytest.approx(100.0)}


def test_every_player_gets_an_entry_in_order() -> None:
    frame = frames(row(player_idx=2), row(player_idx=0))
    assert list(time_average(frame, in_motion(), pl.col("boost"))) == [0, 2]
