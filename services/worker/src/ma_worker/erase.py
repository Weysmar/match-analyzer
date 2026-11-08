"""The `gc_match` job: a match nobody holds any more disappears, files included (section 11 of
CLAUDE.md). The API queues one per match when an account or a session is erased, and the purge
when a session expires: the worker decides, since someone else may hold the match, or bring it
back in the meantime.
"""

import logging
import uuid

from ma_worker.queue import Connection, Job
from ma_worker.runner import PermanentError
from ma_worker.store import ObjectStore

log = logging.getLogger("ma_worker")


def handle(connection: Connection, job: Job, store: ObjectStore) -> None:
    try:
        match_id = uuid.UUID(job.payload["match_id"])
    except KeyError, ValueError, TypeError, AttributeError:
        raise PermanentError("bad_payload") from None
    with connection.transaction():
        # Locked until the end: an upload linking the match now waits, then finds it gone and
        # starts afresh, instead of pointing at deleted files.
        row = connection.execute(
            "SELECT raw_key, raw_deleted_at IS NULL, frames_key, events_key FROM matches "
            "WHERE id = %s FOR UPDATE",
            (match_id,),
        ).fetchone()
        if row is None:
            return
        held = connection.execute(
            "SELECT EXISTS (SELECT FROM user_matches WHERE match_id = %s)", (match_id,)
        ).fetchone()
        if held is not None and held[0]:
            return
        raw_key, raw_kept, frames_key, events_key = row
        # Files first: a store that fails rolls everything back, and the job tries again later.
        # The other way round, a failure would leave files that nothing points to.
        for key in (raw_key if raw_kept else None, frames_key, events_key):
            if key is not None:
                store.delete(key)
        connection.execute("DELETE FROM matches WHERE id = %s", (match_id,))
    log.info("match %s erased", match_id)
