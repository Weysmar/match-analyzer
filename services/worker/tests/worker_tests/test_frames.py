"""The network stream: `parsed`, `header_only`, and merging the roster with the header."""

import logging
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from ma_db.testing import Connection, Factory, count
from ma_worker import parse
from ma_worker.queue import Job
from ma_worker.runner import PermanentError
from ma_worker.settings import Settings
from ma_worker.store import StoreError

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


def dropped(
    conn: Connection, make: Factory, store: MemoryStore, *, user: uuid.UUID | None = None
) -> uuid.UUID:
    session = None if user is not None else make.anonymous_session()
    upload = make.upload(user_id=user, anonymous_session_id=session)
    conn.execute(
        "UPDATE uploads SET status = 'uploaded', declared_size = %s WHERE id = %s",
        (len(REPLAY), upload),
    )
    store.objects[f"incoming/{upload}"] = REPLAY
    return upload


def run_job(
    worker_conn: Connection, store: MemoryStore, settings: Settings, upload: uuid.UUID
) -> None:
    parse.handle(worker_conn, Job(1, "parse", {"upload_id": str(upload)}, 1, 3), store, settings)


def match_of(conn: Connection, upload: uuid.UUID) -> uuid.UUID:
    row = conn.execute("SELECT match_id FROM uploads WHERE id = %s", (upload,)).fetchone()
    assert row is not None
    assert row[0] is not None
    match: uuid.UUID = row[0]
    return match


def match_row(conn: Connection, match: uuid.UUID) -> tuple[Any, ...]:
    row = conn.execute(
        "SELECT status, error_code, frames_key, events_key, arena_out_of_bounds, playlist, "
        "score_blue, score_orange FROM matches WHERE id = %s",
        (match,),
    ).fetchone()
    assert row is not None
    return tuple(row)


def players_of(conn: Connection, match: uuid.UUID) -> list[tuple[Any, ...]]:
    return conn.execute(
        "SELECT frames_idx, platform, platform_id, display_name, team, score, is_bot, anonymized "
        "FROM match_players WHERE match_id = %s ORDER BY frames_idx NULLS LAST, id",
        (match,),
    ).fetchall()


def test_a_readable_network_gives_a_parsed_match(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
) -> None:
    upload = dropped(conn, make, store)
    run_job(worker_conn, store, settings, upload)
    match = match_of(conn, upload)
    frames_key, events_key = f"frames/{match}.parquet", f"events/{match}.json"
    assert match_row(conn, match) == ("parsed", None, frames_key, events_key, False, "13", 1, 0)
    assert store.objects[frames_key] == b"a parquet file"
    assert b'"roster"' in store.objects[events_key]
    assert f"incoming/{upload}" not in store.objects


def test_the_analysis_is_queued_next(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
) -> None:
    upload = dropped(conn, make, store)
    run_job(worker_conn, store, settings, upload)
    jobs = conn.execute(
        "SELECT status, payload->>'match_id' FROM jobs WHERE kind = 'analyze'"
    ).fetchall()
    assert jobs == [("queued", str(match_of(conn, upload)))]


def test_goals_and_demolitions_come_from_the_network(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
) -> None:
    upload = dropped(conn, make, store)
    run_job(worker_conn, store, settings, upload)
    rows = conn.execute(
        """
        SELECT event.kind, event.frame, event.time_s, event.team, actor.display_name,
               victim.display_name
        FROM match_events event
        LEFT JOIN match_players actor ON actor.id = event.actor_player_id
        LEFT JOIN match_players victim ON victim.id = event.victim_player_id
        WHERE event.match_id = %s ORDER BY event.frame
        """,
        (match_of(conn, upload),),
    ).fetchall()
    assert rows == [
        ("demolition", 50, 5.0, 1, "Orange One", "Blue One"),
        ("goal", 100, 12.5, 0, "Blue One", None),
    ]


def test_the_header_gives_the_numbers_and_the_roster_the_rest(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
) -> None:
    upload = dropped(conn, make, store)
    run_job(worker_conn, store, settings, upload)
    assert players_of(conn, match_of(conn, upload)) == [
        (0, "steam", "1001", "Blue One", 0, 100, False, False),
        (1, "epic", "abc", "Orange One", 1, 100, False, False),
    ]


@pytest.mark.parametrize(
    ("code", "error"),
    [
        (12, "network_failed"),
        (13, "processor_failed"),
        (14, "unsupported_mode"),
        (101, "parser_crashed"),
        (1, "parser_crashed"),
    ],
)
def test_a_broken_network_gives_a_header_only_match(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
    fake_parser: FakeParser,
    code: int,
    error: str,
) -> None:
    fake_parser.set_frames_exit_code(code)
    upload = dropped(conn, make, store)
    run_job(worker_conn, store, settings, upload)
    match = match_of(conn, upload)
    # The score stays there to show.
    assert match_row(conn, match) == ("header_only", error, None, None, False, None, 1, 0)
    status = conn.execute("SELECT status FROM uploads WHERE id = %s", (upload,)).fetchone()
    assert status == ("done",)
    # The goals of the header, the file kept to parse again later, and no analysis to wait for.
    assert count(conn, "SELECT count(*) FROM match_events WHERE match_id = %s", match) == 1
    raw = conn.execute("SELECT raw_key FROM matches WHERE id = %s", (match,)).fetchone()
    assert raw is not None
    assert raw[0] in store.objects
    assert count(conn, "SELECT count(*) FROM jobs WHERE kind = 'analyze'") == 0
    assert not any(key.startswith(("frames/", "events/")) for key in store.objects)


def test_a_parser_killed_by_a_signal_gives_a_header_only_match(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
    fake_parser: FakeParser,
) -> None:
    fake_parser.set_frames_signal(9)
    upload = dropped(conn, make, store)
    run_job(worker_conn, store, settings, upload)
    assert match_row(conn, match_of(conn, upload))[:2] == ("header_only", "parser_crashed")


def test_a_parser_out_of_time_gives_a_header_only_match(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
    fake_parser: FakeParser,
) -> None:
    fake_parser.set_frames_hang()
    upload = dropped(conn, make, store)
    run_job(worker_conn, store, replace(settings, parser_timeout_s=1), upload)
    assert match_row(conn, match_of(conn, upload))[:2] == ("header_only", "parser_timeout")


@pytest.mark.parametrize("output", [b"not json", b"[]", b'{"schema_version": 1}'])
def test_events_off_their_schema_give_a_header_only_match(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
    fake_parser: FakeParser,
    output: bytes,
) -> None:
    """A patch can do this. The match still shows its score, and can be parsed again."""
    fake_parser.set_raw_events(output)
    upload = dropped(conn, make, store)
    run_job(worker_conn, store, settings, upload)
    assert match_row(conn, match_of(conn, upload))[:2] == ("header_only", "invalid_events")


def test_missing_frames_give_a_header_only_match(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
    fake_parser: FakeParser,
) -> None:
    fake_parser.set_no_frames_file()
    upload = dropped(conn, make, store)
    run_job(worker_conn, store, settings, upload)
    assert match_row(conn, match_of(conn, upload))[:2] == ("header_only", "invalid_events")


def test_an_output_error_on_frames_is_tried_again(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
    fake_parser: FakeParser,
) -> None:
    fake_parser.set_frames_exit_code(15)
    upload = dropped(conn, make, store)
    with pytest.raises(parse.ParserOutputError):
        run_job(worker_conn, store, settings, upload)
    # Nothing was written: the match only exists once its fate is known.
    assert count(conn, "SELECT count(*) FROM matches") == 0
    fake_parser.set_frames_exit_code(None)
    run_job(worker_conn, store, settings, upload)
    assert match_row(conn, match_of(conn, upload))[0] == "parsed"


def test_bad_arguments_on_frames_are_our_bug(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
    fake_parser: FakeParser,
) -> None:
    fake_parser.set_frames_exit_code(2)
    upload = dropped(conn, make, store)
    with pytest.raises(PermanentError) as failure:
        run_job(worker_conn, store, settings, upload)
    assert failure.value.code == "parser_bad_arguments"


def test_a_store_failure_after_the_frames_leaves_a_clean_retry(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
) -> None:
    upload = dropped(conn, make, store)
    store.broken.add("upload")
    with pytest.raises(StoreError):
        run_job(worker_conn, store, settings, upload)
    assert count(conn, "SELECT count(*) FROM matches") == 0
    store.broken.clear()
    run_job(worker_conn, store, settings, upload)
    match = match_of(conn, upload)
    assert match_row(conn, match)[0] == "parsed"
    assert sum(key.startswith("frames/") for key in store.objects) == 1


def test_a_second_file_of_a_match_is_not_read_again(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
    fake_parser: FakeParser,
) -> None:
    first = dropped(conn, make, store)
    run_job(worker_conn, store, settings, first)
    runs = fake_parser.run_count()
    second = dropped(conn, make, store)
    store.objects[f"incoming/{second}"] = REPLAY
    run_job(worker_conn, store, settings, second)
    assert fake_parser.run_count() == runs
    assert match_of(conn, second) == match_of(conn, first)


def test_the_frame_cap_reaches_the_parser(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
    fake_parser: FakeParser,
) -> None:
    run_job(worker_conn, store, replace(settings, parser_max_fps=30), dropped(conn, make, store))
    assert "--frames --input input.replay --output-dir out --fps 30" in fake_parser.runs.read_text(
        encoding="utf-8"
    )


def test_no_cap_keeps_every_frame(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
    fake_parser: FakeParser,
) -> None:
    run_job(worker_conn, store, settings, dropped(conn, make, store))
    assert "--fps" not in fake_parser.runs.read_text(encoding="utf-8")


def test_an_anonymized_player_shows_their_anonymous_name_only(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
    fake_parser: FakeParser,
) -> None:
    fake_parser.set_events(
        events(
            roster=[
                member(0, "Blue One", 0, "steam", "1001"),
                member(1, "A hidden name", 1, "epic", "abc", anonymized=True),
            ]
        )
    )
    upload = dropped(conn, make, store)
    run_job(worker_conn, store, settings, upload)
    match = match_of(conn, upload)
    assert players_of(conn, match)[1] == (1, "epic", "abc", "A hidden name", 1, 100, False, True)
    assert (
        count(
            conn,
            "SELECT count(*) FROM match_players "
            "WHERE match_id = %s AND display_name = 'Orange One'",
            match,
        )
        == 0
    )


def test_a_real_name_stays_out_when_the_header_cannot_be_told_apart(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
    fake_parser: FakeParser,
) -> None:
    """An old replay: no id in the header, and a hidden name that differs from the real one. The
    header's line could only be this player, under the name they asked to hide."""
    fake_parser.set_header(
        header(
            players=[player("Blue One", 0, "steam", "1001"), player("Real Name", 1, "epic", None)]
        )
    )
    fake_parser.set_events(
        events(
            roster=[
                member(0, "Blue One", 0, "steam", "1001"),
                member(1, "anonymous", 1, "epic", "abc", anonymized=True),
            ]
        )
    )
    upload = dropped(conn, make, store)
    run_job(worker_conn, store, settings, upload)
    names = [row[3] for row in players_of(conn, match_of(conn, upload))]
    assert names == ["Blue One", "anonymous"]


def test_a_player_only_on_the_roster_is_added(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
    fake_parser: FakeParser,
) -> None:
    """The header's list can be incomplete (A7): the roster is the one to trust."""
    fake_parser.set_events(
        events(
            roster=[
                member(0, "Blue One", 0, "steam", "1001"),
                member(1, "Orange One", 1, "epic", "abc"),
                member(2, "Left Early", 1, "xbox", "x-1"),
            ]
        )
    )
    upload = dropped(conn, make, store)
    run_job(worker_conn, store, settings, upload)
    assert players_of(conn, match_of(conn, upload))[2] == (
        2,
        "xbox",
        "x-1",
        "Left Early",
        1,
        None,
        False,
        False,
    )


def test_a_player_only_in_the_header_is_kept(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
    fake_parser: FakeParser,
) -> None:
    fake_parser.set_events(
        events(roster=[member(0, "Blue One", 0, "steam", "1001")], demolitions=[])
    )
    upload = dropped(conn, make, store)
    run_job(worker_conn, store, settings, upload)
    assert players_of(conn, match_of(conn, upload))[1] == (
        None,
        "epic",
        "abc",
        "Orange One",
        1,
        100,
        False,
        False,
    )


def test_an_old_epic_player_is_recognized_by_name(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
    fake_parser: FakeParser,
) -> None:
    fake_parser.set_header(
        header(
            players=[
                player("Blue One", 0, "steam", "1001"),
                player("Old Epic", 1, "epic", None, score=7),
            ]
        )
    )
    fake_parser.set_events(
        events(
            roster=[
                member(0, "Blue One", 0, "steam", "1001"),
                member(1, "Old Epic", 1, "epic", "from-network"),
            ]
        )
    )
    upload = dropped(conn, make, store)
    run_job(worker_conn, store, settings, upload)
    rows = players_of(conn, match_of(conn, upload))
    assert len(rows) == 2
    assert rows[1] == (1, "epic", "from-network", "Old Epic", 1, 7, False, False)


def test_a_bot_on_the_roster_is_a_bot(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
    fake_parser: FakeParser,
) -> None:
    fake_parser.set_events(
        events(
            roster=[
                member(0, "Blue One", 0, "steam", "1001"),
                member(1, "Orange One", 1, "epic", "abc"),
                member(2, "A Bot", 1, "bot", None),
            ]
        )
    )
    upload = dropped(conn, make, store)
    run_job(worker_conn, store, settings, upload)
    assert players_of(conn, match_of(conn, upload))[2][6] is True


def test_an_id_only_the_network_holds_can_verify_a_match(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
    fake_parser: FakeParser,
) -> None:
    user = make.user()
    make.linked_account(user, "epic", "from-network")
    fake_parser.set_header(header(players=[player("Old Epic", 0, "epic", None)], goals=[]))
    fake_parser.set_events(
        events(roster=[member(0, "Old Epic", 0, "epic", "from-network")], goals=[], demolitions=[])
    )
    run_job(worker_conn, store, settings, dropped(conn, make, store, user=user))
    row = conn.execute(
        "SELECT identity_source, verified FROM user_matches WHERE user_id = %s", (user,)
    ).fetchone()
    assert row == ("linked_account", True)


def test_a_breaking_patch_can_be_spotted_in_the_log(
    conn: Connection,
    worker_conn: Connection,
    make: Factory,
    store: MemoryStore,
    settings: Settings,
    fake_parser: FakeParser,
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake_parser.set_frames_exit_code(12)
    with caplog.at_level(logging.INFO, logger="ma_worker"):
        run_job(worker_conn, store, settings, dropped(conn, make, store))
    assert "network_failed" in caplog.text
    assert "260918.75141.528314" in caplog.text
    for secret in ("Blue One", "Orange One", "1001", "A-MATCH-GUID"):
        assert secret not in caplog.text
