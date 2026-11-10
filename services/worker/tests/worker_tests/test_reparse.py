"""The `reparse` job: a match parsed again, its players' identities kept. A stand-in parser in the
real sandbox, and the worker's own role."""

import logging
import uuid
from pathlib import Path
from typing import Any

import pytest

from ma_db.testing import Connection, Factory, count
from ma_worker import parse, reparse
from ma_worker.queue import Job
from ma_worker.runner import PermanentError
from ma_worker.settings import Settings

from .helpers import REPLAY, FakeParser, MemoryStore, events, header, member, player

pytestmark = pytest.mark.db


@pytest.fixture
def fake_parser(tmp_path: Path) -> FakeParser:
    parser = FakeParser(tmp_path)
    parser.set_events(events())
    return parser


@pytest.fixture
def settings(fake_parser: FakeParser) -> Settings:
    return Settings(database_url="unused", parser_bin=str(fake_parser.path), parser_timeout_s=10)


@pytest.fixture
def store() -> MemoryStore:
    return MemoryStore()


def parsed(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
    *,
    user: uuid.UUID,
) -> uuid.UUID:
    """A match parsed once, by an older parser, and linked to `user`."""
    upload = make.upload(user_id=user)
    conn.execute(
        "UPDATE uploads SET status = 'uploaded', declared_size = %s WHERE id = %s",
        (len(REPLAY), upload),
    )
    store.objects[f"incoming/{upload}"] = REPLAY
    parse.handle(worker_conn, Job(1, "parse", {"upload_id": str(upload)}, 1, 3), store, settings)
    row = conn.execute("SELECT match_id FROM uploads WHERE id = %s", (upload,)).fetchone()
    assert row is not None
    match: uuid.UUID = row[0]
    conn.execute("UPDATE matches SET parser_version = '0.0.1' WHERE id = %s", (match,))
    conn.execute("DELETE FROM jobs")
    return match


def run_job(
    worker_conn: Connection, store: MemoryStore, settings: Settings, match: uuid.UUID
) -> None:
    reparse.handle(worker_conn, Job(1, "reparse", {"match_id": str(match)}, 1, 3), store, settings)


def players_of(conn: Connection, match: uuid.UUID) -> dict[str, tuple[Any, ...]]:
    rows = conn.execute(
        "SELECT display_name, id, frames_idx, team, score FROM match_players WHERE match_id = %s",
        (match,),
    ).fetchall()
    return {row[0]: tuple(row[1:]) for row in rows}


def link_of(conn: Connection, user: uuid.UUID) -> tuple[Any, ...]:
    row = conn.execute(
        "SELECT match_player_id, identity_source, verified FROM user_matches WHERE user_id = %s",
        (user,),
    ).fetchone()
    assert row is not None
    return tuple(row)


def test_a_match_is_parsed_again_by_the_new_parser(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
    fake_parser: FakeParser,
) -> None:
    match = parsed(conn, worker_conn, make, store, settings, user=make.user())
    fake_parser.set_header(header(parser_version="0.1.2", score={"blue": 1, "orange": 0}))
    run_job(worker_conn, store, settings, match)
    row = conn.execute(
        "SELECT status, parser_version, analysis_version, analyzed_at, error_code FROM matches "
        "WHERE id = %s",
        (match,),
    ).fetchone()
    assert row == ("parsed", "0.1.2", None, None, None)
    jobs = conn.execute("SELECT kind, payload->>'match_id' FROM jobs").fetchall()
    assert jobs == [("analyze", str(match))]


def test_players_keep_their_ids_and_take_the_new_values(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
    fake_parser: FakeParser,
) -> None:
    match = parsed(conn, worker_conn, make, store, settings, user=make.user())
    before = players_of(conn, match)
    fake_parser.set_header(
        header(
            players=[
                player("Blue One", 0, "steam", "1001", score=999),
                player("Orange One", 1, "epic", "abc", score=5),
            ]
        )
    )
    run_job(worker_conn, store, settings, match)
    after = players_of(conn, match)
    assert {name: values[0] for name, values in after.items()} == {
        name: values[0] for name, values in before.items()
    }
    assert after["Blue One"][3] == 999


def test_a_chosen_identity_survives(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
) -> None:
    user = make.user()
    match = parsed(conn, worker_conn, make, store, settings, user=user)
    chosen = players_of(conn, match)["Orange One"][0]
    conn.execute(
        "UPDATE user_matches SET match_player_id = %s, identity_source = 'claimed' "
        "WHERE user_id = %s",
        (chosen, user),
    )
    run_job(worker_conn, store, settings, match)
    assert link_of(conn, user) == (chosen, "claimed", False)


def test_a_verified_match_stays_verified(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
) -> None:
    user = make.user()
    make.linked_account(user, "steam", "1001")
    match = parsed(conn, worker_conn, make, store, settings, user=user)
    blue = players_of(conn, match)["Blue One"][0]
    assert link_of(conn, user) == (blue, "linked_account", True)
    run_job(worker_conn, store, settings, match)
    assert link_of(conn, user) == (blue, "linked_account", True)


def test_a_player_found_again_by_name_keeps_their_id(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
    fake_parser: FakeParser,
) -> None:
    """An old Epic player with no id: found again by name and team."""
    no_id = header(players=[player("Blue One", 0, "steam", "1001"), player("Old", 1, "epic", None)])
    fake_parser.set_header(no_id)
    fake_parser.set_frames_exit_code(12)
    match = parsed(conn, worker_conn, make, store, settings, user=make.user())
    before = players_of(conn, match)["Old"][0]
    run_job(worker_conn, store, settings, match)
    assert players_of(conn, match)["Old"][0] == before


def test_a_player_no_longer_there_frees_the_links_on_them(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
    fake_parser: FakeParser,
) -> None:
    user = make.user()
    match = parsed(conn, worker_conn, make, store, settings, user=user)
    gone = players_of(conn, match)["Orange One"][0]
    conn.execute(
        "UPDATE user_matches SET match_player_id = %s, identity_source = 'claimed' "
        "WHERE user_id = %s",
        (gone, user),
    )
    fake_parser.set_header(header(players=[player("Blue One", 0, "steam", "1001")]))
    fake_parser.set_events(events(roster=[member(0, "Blue One", 0, "steam", "1001")]))
    run_job(worker_conn, store, settings, match)
    assert "Orange One" not in players_of(conn, match)
    assert link_of(conn, user) == (None, "none", False)


def test_a_memorized_player_is_applied_again(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
) -> None:
    user = make.user()
    match = parsed(conn, worker_conn, make, store, settings, user=user)
    conn.execute(
        "INSERT INTO player_claims (user_id, platform, platform_id) VALUES (%s, 'epic', 'abc')",
        (user,),
    )
    run_job(worker_conn, store, settings, match)
    orange = players_of(conn, match)["Orange One"][0]
    assert link_of(conn, user) == (orange, "memorized", False)


def test_old_metrics_go_and_events_are_not_doubled(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
) -> None:
    match = parsed(conn, worker_conn, make, store, settings, user=make.user())
    make.metric(players_of(conn, match)["Blue One"][0], "boost.avg", 50.0)
    make.team_metric(match, 0)
    make.situation(match)
    old_view = f"views/{match}.json.gz"
    store.objects[old_view] = b"drawn from the previous parse"
    conn.execute("UPDATE matches SET view_key = %s WHERE id = %s", (old_view, match))
    events_before = count(conn, "SELECT count(*) FROM match_events WHERE match_id = %s", match)
    run_job(worker_conn, store, settings, match)
    assert count(conn, "SELECT count(*) FROM player_match_metrics") == 0
    assert count(conn, "SELECT count(*) FROM team_match_metrics") == 0
    assert count(conn, "SELECT count(*) FROM match_situations") == 0
    # The old view goes with them, until the analysis queued here draws it again.
    assert old_view not in store.objects
    assert conn.execute("SELECT view_key FROM matches WHERE id = %s", (match,)).fetchone() == (
        None,
    )
    assert count(conn, "SELECT count(*) FROM match_events WHERE match_id = %s", match) == (
        events_before
    )


def test_a_network_that_no_longer_reads_gives_header_only(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
    fake_parser: FakeParser,
) -> None:
    match = parsed(conn, worker_conn, make, store, settings, user=make.user())
    fake_parser.set_frames_exit_code(12)
    run_job(worker_conn, store, settings, match)
    row = conn.execute(
        "SELECT status, error_code, frames_key FROM matches WHERE id = %s", (match,)
    ).fetchone()
    assert row == ("header_only", "network_failed", None)
    assert count(conn, "SELECT count(*) FROM jobs WHERE kind = 'analyze'") == 0


def test_a_purged_raw_file_leaves_the_match_as_it_was(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
    caplog: pytest.LogCaptureFixture,
) -> None:
    match = parsed(conn, worker_conn, make, store, settings, user=make.user())
    conn.execute("UPDATE matches SET raw_deleted_at = now() WHERE id = %s", (match,))
    with caplog.at_level(logging.WARNING, logger="ma_worker"):
        run_job(worker_conn, store, settings, match)
    assert "no raw file left" in caplog.text
    row = conn.execute("SELECT parser_version FROM matches WHERE id = %s", (match,)).fetchone()
    assert row == ("0.0.1",)


def test_a_raw_file_missing_from_the_store_is_the_same(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
) -> None:
    match = parsed(conn, worker_conn, make, store, settings, user=make.user())
    store.objects = {k: v for k, v in store.objects.items() if not k.startswith("raw/")}
    run_job(worker_conn, store, settings, match)
    row = conn.execute("SELECT parser_version FROM matches WHERE id = %s", (match,)).fetchone()
    assert row == ("0.0.1",)


def test_a_header_the_new_parser_cannot_read_stops_the_job(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
    fake_parser: FakeParser,
) -> None:
    match = parsed(conn, worker_conn, make, store, settings, user=make.user())
    before = players_of(conn, match)
    fake_parser.set_exit_code(11)
    with pytest.raises(PermanentError) as failure:
        run_job(worker_conn, store, settings, match)
    assert failure.value.code == "reparse_header_failed"
    assert players_of(conn, match) == before


def test_a_match_erased_meanwhile_is_fine(
    worker_conn: Connection, store: MemoryStore, settings: Settings
) -> None:
    run_job(worker_conn, store, settings, uuid.uuid4())


def test_nothing_personal_reaches_the_log(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
    caplog: pytest.LogCaptureFixture,
) -> None:
    match = parsed(conn, worker_conn, make, store, settings, user=make.user())
    with caplog.at_level(logging.INFO, logger="ma_worker"):
        run_job(worker_conn, store, settings, match)
    assert "parsed again" in caplog.text
    for secret in ("Blue One", "Orange One", "1001", "A-MATCH-GUID"):
        assert secret not in caplog.text
