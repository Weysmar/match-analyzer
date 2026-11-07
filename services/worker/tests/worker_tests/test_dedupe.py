"""The second level of deduplication, and the small pure parts of the job. No database needed."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest

from ma_schemas import HeaderDocument, problems
from ma_worker.dedupe import dedupe_key
from ma_worker.load import played_at_utc
from ma_worker.parse import file_sha256, looks_like_a_replay

from .helpers import REPLAY, header, player

SHA = "a" * 64
OTHER_SHA = "b" * 64


def key(sha: str = SHA, **fields: Any) -> str:
    return dedupe_key(cast(HeaderDocument, header(**fields)), sha)


def test_the_test_header_is_valid() -> None:
    assert problems("header", header()) == []


def test_two_files_of_one_match_have_one_key() -> None:
    assert key(SHA) == key(OTHER_SHA)


def test_the_order_of_players_does_not_matter() -> None:
    players = header()["players"]
    assert key(players=players) == key(players=list(reversed(players)))


def test_what_only_one_file_says_does_not_matter() -> None:
    """Teammates' replays differ in their build, their date source or their replay id."""
    assert key() == key(replay_id="ANOTHER", duration_s=299.0, game_build="another")


@pytest.mark.parametrize(
    "fields",
    [
        {"match_guid": "ANOTHER"},
        {"score": {"blue": 0, "orange": 1}},
        {"players": [player("Blue One", 0, "steam", "1001")]},
        {"players": [player("Blue One", 0, "steam", "9999"), player("O", 1, "epic", "abc")]},
        {"players": [player("Blue One", 0, "epic", "1001"), player("O", 1, "epic", "abc")]},
        {"players": [player("Blue One", 1, "steam", "1001"), player("O", 1, "epic", "abc")]},
    ],
)
def test_a_different_match_has_another_key(fields: dict[str, Any]) -> None:
    assert key(**fields) != key()


def test_the_date_stands_in_for_a_missing_guid() -> None:
    assert key(SHA, match_guid=None) == key(OTHER_SHA, match_guid=None)
    assert key(match_guid=None) != key(match_guid=None, played_at="2026-11-01T21:00:00Z")


def test_a_name_stands_in_for_a_missing_id() -> None:
    def with_name(name: str) -> list[Any]:
        return [player(name, 0, "epic", None)]

    assert key(players=with_name("A")) == key(players=with_name("A"))
    assert key(players=with_name("A")) != key(players=with_name("B"))


@pytest.mark.parametrize(
    "fields",
    [
        {"match_guid": None, "played_at": None, "played_at_source": None},
        {"players": []},
    ],
)
def test_a_file_with_nothing_to_tell_it_apart_only_matches_itself(fields: dict[str, Any]) -> None:
    assert key(SHA, **fields) != key(OTHER_SHA, **fields)
    assert key(SHA, **fields) == key(SHA, **fields)


def test_the_key_fits_its_column() -> None:
    assert len(key()) == 64


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-11-01T20:00:00Z", datetime(2026, 11, 1, 20, 0, tzinfo=UTC)),
        ("2026-11-01T20:00:00", datetime(2026, 11, 1, 20, 0, tzinfo=UTC)),
        (None, None),
    ],
)
def test_played_at_is_always_utc(value: str | None, expected: datetime | None) -> None:
    assert played_at_utc(cast(HeaderDocument, header(played_at=value))) == expected


def test_a_replay_is_recognized(tmp_path: Path) -> None:
    path = tmp_path / "file"
    path.write_bytes(REPLAY)
    assert looks_like_a_replay(path)


@pytest.mark.parametrize(
    "content", [b"", b"not a replay", b"\x00" * 300 + b"TAGame.Replay_Soccar_TA"]
)
def test_a_fake_is_recognized(tmp_path: Path, content: bytes) -> None:
    path = tmp_path / "file"
    path.write_bytes(content)
    assert not looks_like_a_replay(path)


def test_the_hash_is_the_files(tmp_path: Path) -> None:
    path = tmp_path / "file"
    path.write_bytes(b"abc")
    expected = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert file_sha256(path) == expected
