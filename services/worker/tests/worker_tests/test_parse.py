"""The `parse` job, with a stand-in parser in the real sandbox, and the worker's own role."""

import hashlib
import logging
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
import pytest

from ma_db.testing import Connection, Factory, count
from ma_worker import parse, queue
from ma_worker.queue import Job
from ma_worker.runner import PermanentError, Runner
from ma_worker.settings import Settings
from ma_worker.store import StoreError

from .helpers import REPLAY, FakeParser, MemoryStore, header, player

pytestmark = pytest.mark.db

OTHER_REPLAY = REPLAY + b" and more"


@pytest.fixture
def fake_parser(tmp_path: Path) -> FakeParser:
    return FakeParser(tmp_path)


@pytest.fixture
def settings(fake_parser: FakeParser) -> Settings:
    return Settings(database_url="unused", parser_bin=str(fake_parser.path), parser_timeout_s=10)


@pytest.fixture
def store() -> MemoryStore:
    return MemoryStore()


def dropped(
    make: Factory,
    store: MemoryStore,
    body: bytes = REPLAY,
    *,
    user: uuid.UUID | None = None,
    session: uuid.UUID | None = None,
    conn: Connection,
) -> uuid.UUID:
    """A file in `incoming/`, whose browser said it was done."""
    if user is None and session is None:
        session = make.anonymous_session()
    upload = make.upload(user_id=user, anonymous_session_id=session)
    conn.execute(
        "UPDATE uploads SET status = 'uploaded', declared_size = %s WHERE id = %s",
        (len(body), upload),
    )
    store.objects[f"incoming/{upload}"] = body
    return upload


def run_job(
    worker_conn: Connection,
    store: MemoryStore,
    settings: Settings,
    upload: uuid.UUID,
) -> None:
    job = Job(1, "parse", {"upload_id": str(upload)}, 1, 3)
    parse.handle(worker_conn, job, store, settings)


def upload_row(conn: Connection, upload: uuid.UUID) -> dict[str, Any]:
    row = conn.execute(
        "SELECT status, rejection, sha256, match_id, completed_at IS NOT NULL FROM uploads "
        "WHERE id = %s",
        (upload,),
    ).fetchone()
    assert row is not None
    names = ("status", "rejection", "sha256", "match_id", "completed")
    return dict(zip(names, row, strict=True))


def matches_count(conn: Connection) -> int:
    return count(conn, "SELECT count(*) FROM matches")


def test_a_good_file_becomes_a_match(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
) -> None:
    upload = dropped(make, store, conn=conn)
    run_job(worker_conn, store, settings, upload)

    sha = hashlib.sha256(REPLAY).hexdigest()
    state = upload_row(conn, upload)
    assert state["status"] == "done"
    assert state["sha256"] == sha
    assert state["completed"] is True
    match = state["match_id"]
    row = conn.execute(
        """
        SELECT status, match_guid, game_build, build_id, changelist, replay_major, replay_minor,
               replay_net, map, played_at, played_at_source, duration_s, match_type, team_size,
               score_blue, score_orange, raw_key, parser_version, parsed_at IS NOT NULL
        FROM matches WHERE id = %s
        """,
        (match,),
    ).fetchone()
    assert row == (
        "header_only",
        "A-MATCH-GUID",
        "260918.75141.528314",
        1,
        2,
        868,
        34,
        12,
        "a_map",
        datetime(2026, 11, 1, 20, 0, tzinfo=UTC),
        "epoch",
        300.0,
        "Online",
        1,
        1,
        0,
        f"raw/{sha}.replay",
        "0.1.1",
        True,
    )
    players = conn.execute(
        "SELECT platform, platform_id, display_name, team, score, goals, is_bot, anonymized, "
        "frames_idx FROM match_players WHERE match_id = %s ORDER BY team",
        (match,),
    ).fetchall()
    assert players == [
        ("steam", "1001", "Blue One", 0, 100, 1, False, False, None),
        ("epic", "abc", "Orange One", 1, 100, 0, False, False, None),
    ]
    goals = conn.execute(
        """
        SELECT event.kind, event.frame, event.time_s, event.team, player.display_name
        FROM match_events event JOIN match_players player ON player.id = event.actor_player_id
        WHERE event.match_id = %s
        """,
        (match,),
    ).fetchall()
    assert goals == [("goal", 100, 12.5, 0, "Blue One")]
    assert count(conn, "SELECT count(*) FROM match_files WHERE sha256 = %s", sha) == 1


def test_the_file_moves_from_incoming_to_raw(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
) -> None:
    upload = dropped(make, store, conn=conn)
    run_job(worker_conn, store, settings, upload)
    sha = hashlib.sha256(REPLAY).hexdigest()
    assert store.objects == {f"raw/{sha}.replay": REPLAY}


def test_the_parser_gets_a_folder_of_its_own(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
    fake_parser: FakeParser,
) -> None:
    run_job(worker_conn, store, settings, dropped(make, store, conn=conn))
    assert fake_parser.runs.read_text(encoding="utf-8") == (
        "--header --input input.replay --output header.json\n"
    )


def test_the_owner_is_linked(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
) -> None:
    session = make.anonymous_session()
    upload = dropped(make, store, session=session, conn=conn)
    run_job(worker_conn, store, settings, upload)
    match = upload_row(conn, upload)["match_id"]
    assert (
        count(
            conn,
            "SELECT count(*) FROM user_matches WHERE anonymous_session_id = %s AND match_id = %s",
            session,
            match,
        )
        == 1
    )


@pytest.mark.parametrize("body", [b"this is not a replay at all", b"x"])
def test_a_fake_is_rejected_without_running_the_parser(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
    fake_parser: FakeParser,
    body: bytes,
) -> None:
    upload = dropped(make, store, body, conn=conn)
    run_job(worker_conn, store, settings, upload)
    state = upload_row(conn, upload)
    assert (state["status"], state["rejection"]) == ("rejected", "not_a_replay")
    assert state["completed"] is True
    assert store.objects == {}
    assert fake_parser.run_count() == 0
    assert matches_count(conn) == 0


def test_a_file_of_another_size_is_rejected(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
) -> None:
    upload = dropped(make, store, conn=conn)
    store.objects[f"incoming/{upload}"] = REPLAY + b"x"
    run_job(worker_conn, store, settings, upload)
    state = upload_row(conn, upload)
    assert (state["status"], state["rejection"]) == ("rejected", "size_mismatch")
    assert store.objects == {}


def test_a_file_too_large_is_rejected(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
) -> None:
    upload = dropped(make, store, conn=conn)
    run_job(worker_conn, store, replace(settings, upload_max_bytes=len(REPLAY) - 1), upload)
    state = upload_row(conn, upload)
    assert (state["status"], state["rejection"]) == ("rejected", "too_large")
    assert store.objects == {}


@pytest.mark.parametrize(
    ("code", "rejection"),
    [(10, "not_a_replay"), (11, "corrupt"), (101, "corrupt"), (12, "corrupt")],
)
def test_the_parser_can_reject_a_file(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
    fake_parser: FakeParser,
    code: int,
    rejection: str,
) -> None:
    fake_parser.set_exit_code(code)
    upload = dropped(make, store, conn=conn)
    run_job(worker_conn, store, settings, upload)
    state = upload_row(conn, upload)
    assert (state["status"], state["rejection"]) == ("rejected", rejection)
    assert store.objects == {}


def test_a_parser_that_hangs_gets_the_file_rejected(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
    tmp_path: Path,
) -> None:
    hanging = tmp_path / "hanging"
    hanging.write_text("#!/bin/sh\nsleep 300\n", encoding="utf-8")
    hanging.chmod(0o755)
    upload = dropped(make, store, conn=conn)
    run_job(
        worker_conn,
        store,
        replace(settings, parser_bin=str(hanging), parser_timeout_s=1),
        upload,
    )
    state = upload_row(conn, upload)
    assert (state["status"], state["rejection"]) == ("rejected", "corrupt")


def test_bad_arguments_are_our_bug(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
    fake_parser: FakeParser,
) -> None:
    fake_parser.set_exit_code(2)
    upload = dropped(make, store, conn=conn)
    with pytest.raises(PermanentError) as failure:
        run_job(worker_conn, store, settings, upload)
    assert failure.value.code == "parser_bad_arguments"
    # The file stays: a fixed parser can take it up again.
    assert f"incoming/{upload}" in store.objects


def test_an_output_error_is_tried_again(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
    fake_parser: FakeParser,
) -> None:
    fake_parser.set_exit_code(15)
    upload = dropped(make, store, conn=conn)
    with pytest.raises(parse.ParserOutputError):
        run_job(worker_conn, store, settings, upload)
    assert upload_row(conn, upload)["status"] == "processing"
    fake_parser.set_exit_code(None)
    run_job(worker_conn, store, settings, upload)
    assert upload_row(conn, upload)["status"] == "done"


@pytest.mark.parametrize(
    "output",
    [b"not json", b"[]", b'{"schema_version": 1}', b'{"schema_version": 99}'],
)
def test_a_header_off_its_schema_stops_the_job(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
    fake_parser: FakeParser,
    output: bytes,
) -> None:
    fake_parser.set_raw_output(output)
    upload = dropped(make, store, conn=conn)
    with pytest.raises(PermanentError) as failure:
        run_job(worker_conn, store, settings, upload)
    assert failure.value.code == "invalid_header"
    assert matches_count(conn) == 0


def test_the_same_file_twice_is_one_match_and_two_links(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
    fake_parser: FakeParser,
) -> None:
    first_user, second_user = make.user(), make.user()
    first = dropped(make, store, user=first_user, conn=conn)
    second = dropped(make, store, user=second_user, conn=conn)
    run_job(worker_conn, store, settings, first)
    run_job(worker_conn, store, settings, second)

    match = upload_row(conn, first)["match_id"]
    state = upload_row(conn, second)
    assert state["status"] == "duplicate"
    assert state["match_id"] == match
    assert state["sha256"] == hashlib.sha256(REPLAY).hexdigest()
    assert count(conn, "SELECT count(*) FROM user_matches WHERE match_id = %s", match) == 2
    # The second file is known by its hash: the parser does not even run.
    assert fake_parser.run_count() == 1
    assert list(store.objects) == [f"raw/{state['sha256']}.replay"]


def test_two_files_of_one_match_are_one_match(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
) -> None:
    first_user, second_user = make.user(), make.user()
    first = dropped(make, store, user=first_user, conn=conn)
    second = dropped(make, store, OTHER_REPLAY, user=second_user, conn=conn)
    run_job(worker_conn, store, settings, first)
    run_job(worker_conn, store, settings, second)

    match = upload_row(conn, first)["match_id"]
    state = upload_row(conn, second)
    assert (state["status"], state["match_id"]) == ("duplicate", match)
    assert count(conn, "SELECT count(*) FROM user_matches WHERE match_id = %s", match) == 2
    assert count(conn, "SELECT count(*) FROM match_files WHERE match_id = %s", match) == 2
    # Only the first file is kept.
    assert list(store.objects) == [f"raw/{hashlib.sha256(REPLAY).hexdigest()}.replay"]


def test_bringing_a_match_twice_is_one_link(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
) -> None:
    user = make.user()
    first = dropped(make, store, user=user, conn=conn)
    second = dropped(make, store, user=user, conn=conn)
    run_job(worker_conn, store, settings, first)
    run_job(worker_conn, store, settings, second)
    match = upload_row(conn, first)["match_id"]
    assert count(conn, "SELECT count(*) FROM user_matches WHERE match_id = %s", match) == 1


def test_a_forged_file_with_someones_guid_stays_apart(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
    fake_parser: FakeParser,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Same `MatchGUID`, other score (I10). The incident is logged, with nothing personal."""
    first = dropped(make, store, user=make.user(), conn=conn)
    run_job(worker_conn, store, settings, first)
    fake_parser.set_header(header(score={"blue": 9, "orange": 9}))
    forged = dropped(make, store, OTHER_REPLAY, user=make.user(), conn=conn)
    with caplog.at_level(logging.INFO, logger="ma_worker"):
        run_job(worker_conn, store, settings, forged)
    assert upload_row(conn, forged)["status"] == "done"
    assert upload_row(conn, forged)["match_id"] != upload_row(conn, first)["match_id"]
    assert "shares its guid" in caplog.text
    for secret in ("A-MATCH-GUID", "Blue One", "1001"):
        assert secret not in caplog.text


def test_files_with_nothing_to_tell_them_apart_stay_apart(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
    fake_parser: FakeParser,
) -> None:
    empty = header(match_guid=None, played_at=None, played_at_source=None, players=[], goals=[])
    fake_parser.set_header(empty)
    first = dropped(make, store, conn=conn)
    second = dropped(make, store, OTHER_REPLAY, conn=conn)
    run_job(worker_conn, store, settings, first)
    run_job(worker_conn, store, settings, second)
    assert upload_row(conn, first)["match_id"] != upload_row(conn, second)["match_id"]


def test_a_date_without_a_time_zone_is_kept(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
    fake_parser: FakeParser,
) -> None:
    fake_parser.set_header(
        header(played_at="2026-11-01T20:00:00", played_at_source="date_without_timezone")
    )
    upload = dropped(make, store, conn=conn)
    run_job(worker_conn, store, settings, upload)
    row = conn.execute(
        "SELECT played_at, played_at_source FROM matches WHERE id = %s",
        (upload_row(conn, upload)["match_id"],),
    ).fetchone()
    assert row == (datetime(2026, 11, 1, 20, 0, tzinfo=UTC), "date_without_timezone")


def test_a_player_without_a_team_or_a_goal_without_a_time_is_left_out(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
    fake_parser: FakeParser,
) -> None:
    fake_parser.set_header(
        header(
            players=[player("Blue One", 0, "steam", "1001"), player("Nobody", None, "steam", "2")],
            goals=[
                {"frame": 1, "time_s": None, "player_name": "Blue One", "team": 0},
                {"frame": 2, "time_s": 1.0, "player_name": "Unknown", "team": 0},
            ],
        )
    )
    upload = dropped(make, store, conn=conn)
    run_job(worker_conn, store, settings, upload)
    match = upload_row(conn, upload)["match_id"]
    assert count(conn, "SELECT count(*) FROM match_players WHERE match_id = %s", match) == 1
    goals = conn.execute(
        "SELECT frame, actor_player_id FROM match_events WHERE match_id = %s", (match,)
    ).fetchall()
    assert goals == [(2, None)]


def link_of(conn: Connection, user: uuid.UUID) -> tuple[Any, ...]:
    row = conn.execute(
        "SELECT player.display_name, link.identity_source, link.verified "
        "FROM user_matches link LEFT JOIN match_players player ON player.id = link.match_player_id "
        "WHERE link.user_id = %s",
        (user,),
    ).fetchone()
    assert row is not None
    return tuple(row)


def test_a_steam_player_is_identified_and_verified(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
) -> None:
    user = make.user()
    make.linked_account(user, "steam", "1001")
    run_job(worker_conn, store, settings, dropped(make, store, user=user, conn=conn))
    assert link_of(conn, user) == ("Blue One", "linked_account", True)


def test_an_epic_player_is_identified_and_verified(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
) -> None:
    user = make.user()
    make.linked_account(user, "epic", "abc")
    run_job(worker_conn, store, settings, dropped(make, store, user=user, conn=conn))
    assert link_of(conn, user) == ("Orange One", "linked_account", True)


def test_a_memorized_player_is_identified_but_not_verified(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
) -> None:
    user = make.user()
    conn.execute(
        "INSERT INTO player_claims (user_id, platform, platform_id) VALUES (%s, 'steam', '1001')",
        (user,),
    )
    run_job(worker_conn, store, settings, dropped(make, store, user=user, conn=conn))
    assert link_of(conn, user) == ("Blue One", "memorized", False)


def test_an_unknown_player_is_asked_later(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
) -> None:
    user = make.user()
    make.linked_account(user, "steam", "someone-else")
    run_job(worker_conn, store, settings, dropped(make, store, user=user, conn=conn))
    assert link_of(conn, user) == (None, "none", False)


def test_a_second_owner_is_identified_too(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
) -> None:
    first, second = make.user(), make.user()
    make.linked_account(second, "epic", "abc")
    run_job(worker_conn, store, settings, dropped(make, store, user=first, conn=conn))
    run_job(worker_conn, store, settings, dropped(make, store, user=second, conn=conn))
    assert link_of(conn, second) == ("Orange One", "linked_account", True)


def test_an_upload_erased_meanwhile_only_leaves_its_file_to_delete(
    worker_conn: Connection, store: MemoryStore, settings: Settings
) -> None:
    upload = uuid.uuid4()
    store.objects[f"incoming/{upload}"] = REPLAY
    run_job(worker_conn, store, settings, upload)
    assert store.objects == {}


def test_running_again_after_the_end_changes_nothing(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
    fake_parser: FakeParser,
) -> None:
    """A worker dying right after its commit, before deleting the file, is taken up again."""
    upload = dropped(make, store, conn=conn)
    run_job(worker_conn, store, settings, upload)
    store.objects[f"incoming/{upload}"] = REPLAY
    before = matches_count(conn)
    run_job(worker_conn, store, settings, upload)
    assert f"incoming/{upload}" not in store.objects
    assert matches_count(conn) == before
    assert fake_parser.run_count() == 1


@pytest.mark.parametrize("operation", ["download", "copy"])
def test_a_store_failure_is_tried_again_without_harm(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
    operation: str,
) -> None:
    upload = dropped(make, store, conn=conn)
    store.broken.add(operation)
    with pytest.raises(StoreError):
        run_job(worker_conn, store, settings, upload)
    assert upload_row(conn, upload)["match_id"] is None
    store.broken.clear()
    run_job(worker_conn, store, settings, upload)
    assert upload_row(conn, upload)["status"] == "done"


def test_a_failed_delete_after_the_commit_leaves_a_clean_retry(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
) -> None:
    upload = dropped(make, store, conn=conn)
    store.broken.add("delete")
    with pytest.raises(StoreError):
        run_job(worker_conn, store, settings, upload)
    assert upload_row(conn, upload)["status"] == "done"
    store.broken.clear()
    run_job(worker_conn, store, settings, upload)
    assert f"incoming/{upload}" not in store.objects


@pytest.mark.parametrize(
    "payload", [{}, {"upload_id": "not-an-id"}, {"upload_id": None}, {"upload_id": 12}]
)
def test_a_bad_payload_stops_the_job(
    worker_conn: Connection, store: MemoryStore, settings: Settings, payload: dict[str, Any]
) -> None:
    with pytest.raises(PermanentError) as failure:
        parse.handle(worker_conn, Job(1, "parse", payload, 1, 3), store, settings)
    assert failure.value.code == "bad_payload"


def test_nothing_personal_reaches_the_log(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO, logger="ma_worker"):
        run_job(worker_conn, store, settings, dropped(make, store, conn=conn))
    assert "260918.75141.528314" in caplog.text  # The build, to spot a breaking patch.
    for secret in ("Blue One", "Orange One", "1001", "abc", "A-MATCH-GUID"):
        assert secret not in caplog.text


def test_through_the_queue_a_failure_marks_the_upload_failed(
    conn: Connection,
    worker_conn: Connection,
    worker_url: str,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
    fake_parser: FakeParser,
) -> None:
    """Nobody should wait forever for a file whose job has died."""
    fake_parser.set_raw_output(b"not json")
    upload = dropped(make, store, conn=conn)
    conn.execute(
        "INSERT INTO jobs (kind, payload) VALUES ('parse', %s)",
        (f'{{"upload_id": "{upload}"}}',),
    )
    runner = Runner(
        lambda: psycopg.connect(worker_url, autocommit=True),
        {"parse": lambda c, job: parse.handle(c, job, store, settings)},
        "worker-a",
        600,
    )
    assert runner.run_once(worker_conn) is True
    row = conn.execute("SELECT status, last_error FROM jobs").fetchone()
    assert row == ("dead", "invalid_header")
    assert upload_row(conn, upload)["status"] == "failed"
    assert queue.dead_jobs(worker_conn)[0][2] == "invalid_header"
