"""The `gc_match` job, against PostgreSQL with the worker's own role (step 9, T9.8)."""

import uuid

import pytest

from ma_db.testing import Connection, Factory, count
from ma_worker import erase
from ma_worker.queue import Job
from ma_worker.runner import PermanentError
from ma_worker.store import StoreError

from .helpers import MemoryStore

pytestmark = pytest.mark.db


def stored_match(conn: Connection, make: Factory, store: MemoryStore) -> uuid.UUID:
    """A match with its three files in the store, a player, an event and a metric."""
    match = make.match()
    player = make.player(match)
    make.metric(player)
    keys = (f"raw/{match.hex}.replay", f"frames/{match}.parquet", f"events/{match}.json")
    conn.execute(
        "UPDATE matches SET raw_key = %s, frames_key = %s, events_key = %s WHERE id = %s",
        (*keys, match),
    )
    conn.execute(
        "INSERT INTO match_events (match_id, kind, frame, time_s, team) "
        "VALUES (%s, 'goal', 1, 1.0, 0)",
        (match,),
    )
    for key in keys:
        store.objects[key] = b"data"
    return match


def run_job(worker_conn: Connection, store: MemoryStore, match: uuid.UUID | str) -> None:
    erase.handle(worker_conn, Job(1, "gc_match", {"match_id": str(match)}, 1, 3), store)


def test_a_match_nobody_holds_disappears_with_its_files(
    conn: Connection, worker_conn: Connection, make: Factory
) -> None:
    store = MemoryStore()
    match = stored_match(conn, make, store)
    upload = make.upload(user_id=make.user(), match_id=match)
    run_job(worker_conn, store, match)
    assert count(conn, "SELECT count(*) FROM matches WHERE id = %s", match) == 0
    assert count(conn, "SELECT count(*) FROM match_players WHERE match_id = %s", match) == 0
    assert count(conn, "SELECT count(*) FROM match_events WHERE match_id = %s", match) == 0
    assert count(conn, "SELECT count(*) FROM player_match_metrics") == 0
    assert store.objects == {}
    # An upload outlives the match it led to, without pointing at it.
    assert conn.execute("SELECT match_id FROM uploads WHERE id = %s", (upload,)).fetchone() == (
        None,
    )


@pytest.mark.parametrize("holder", ["user", "anonymous"])
def test_a_match_someone_holds_stays(
    conn: Connection, worker_conn: Connection, make: Factory, holder: str
) -> None:
    store = MemoryStore()
    match = stored_match(conn, make, store)
    if holder == "user":
        make.user_match(match, user_id=make.user())
    else:
        make.user_match(match, anonymous_session_id=make.anonymous_session())
    run_job(worker_conn, store, match)
    assert count(conn, "SELECT count(*) FROM matches WHERE id = %s", match) == 1
    assert len(store.objects) == 3


def test_a_raw_file_already_purged_is_not_asked_for(
    conn: Connection, worker_conn: Connection, make: Factory
) -> None:
    store = MemoryStore()
    match = stored_match(conn, make, store)
    conn.execute("UPDATE matches SET raw_deleted_at = now() WHERE id = %s", (match,))
    del store.objects[f"raw/{match.hex}.replay"]
    run_job(worker_conn, store, match)
    assert count(conn, "SELECT count(*) FROM matches WHERE id = %s", match) == 0
    assert store.objects == {}


def test_a_match_already_gone_is_fine(worker_conn: Connection) -> None:
    run_job(worker_conn, MemoryStore(), uuid.uuid4())


def test_a_store_that_fails_keeps_the_match_for_another_try(
    conn: Connection, worker_conn: Connection, make: Factory
) -> None:
    store = MemoryStore()
    match = stored_match(conn, make, store)
    store.broken.add("delete")
    with pytest.raises(StoreError):
        run_job(worker_conn, store, match)
    assert count(conn, "SELECT count(*) FROM matches WHERE id = %s", match) == 1


def test_a_bad_payload_is_dead_at_once(worker_conn: Connection) -> None:
    with pytest.raises(PermanentError):
        run_job(worker_conn, MemoryStore(), "not-a-uuid")
