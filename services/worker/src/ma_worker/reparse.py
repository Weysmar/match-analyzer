"""The `reparse` job: a match parsed again from its raw file, by a newer parser (section 5.2 of
CLAUDE.md).

The match keeps its id, and its players keep theirs: links to users point at them, with the player
each one chose and whether it was verified. Players are updated in place, matched by their platform
id, then their row in the frames, then their name and team. One who is no longer there leaves the
links that pointed at them without an identity, to be chosen again.
"""

import logging
import tempfile
import uuid
from pathlib import Path

from psycopg.types.json import Jsonb

from ma_worker import load, parse, sandbox
from ma_worker.queue import Connection, Job
from ma_worker.runner import PermanentError
from ma_worker.settings import Settings
from ma_worker.store import ObjectStore

log = logging.getLogger("ma_worker")


def _refresh_identities(connection: Connection, match_id: uuid.UUID) -> None:
    """The memorized players and the proofs of every owner of the match, applied afresh."""
    owners = connection.execute(
        "SELECT DISTINCT user_id, anonymous_session_id FROM user_matches WHERE match_id = %s",
        (match_id,),
    ).fetchall()
    for user_id, session_id in owners:
        connection.execute("SELECT apply_player_claims(%s, %s)", (user_id, session_id))
        if user_id is not None:
            connection.execute("SELECT refresh_verification(%s)", (user_id,))


def _read_header_again(settings: Settings, workdir: Path) -> load.HeaderDocument:
    result = sandbox.run(
        settings.parser_bin,
        ["--header", "--input", parse.INPUT, "--output", parse.HEADER],
        workdir,
        sandbox.Limits(timeout_s=settings.parser_timeout_s, memory_mb=settings.parser_memory_mb),
    )
    if result.exit_code == parse.EXIT_OUTPUT_ERROR:
        raise parse.ParserOutputError
    if result.exit_code != parse.EXIT_OK:
        # This file gave a header before: the new parser has a problem with it, not the file.
        raise PermanentError("reparse_header_failed")
    return parse.read_header(workdir)


def handle(connection: Connection, job: Job, store: ObjectStore, settings: Settings) -> None:
    try:
        match_id = uuid.UUID(job.payload["match_id"])
    except KeyError, ValueError, TypeError, AttributeError:
        raise PermanentError("bad_payload") from None
    row = connection.execute(
        "SELECT raw_key, raw_deleted_at FROM matches WHERE id = %s", (match_id,)
    ).fetchone()
    if row is None:
        return
    raw_key, raw_deleted_at = row
    if raw_key is None or raw_deleted_at is not None or store.size(raw_key) is None:
        # Purged after its retention period: the match stays as its last parser left it.
        log.warning("match %s: no raw file left to parse again", match_id)
        return

    with tempfile.TemporaryDirectory(prefix="ma-reparse-") as folder:
        workdir = Path(folder)
        store.download(raw_key, workdir / parse.INPUT, settings.upload_max_bytes)
        header = _read_header_again(settings, workdir)
        frames, error_code = parse.run_frames(store, settings, workdir, match_id)

    events = None if frames is None else frames.events
    with connection.transaction():
        load.update_match(connection, match_id, header, frames, error_code)
        ids = load.replace_players(connection, match_id, load.merge_players(header, events))
        load.replace_events(connection, match_id, header, events, ids)
        # Computed from the previous parse: the analysis starts over.
        connection.execute(
            "DELETE FROM player_match_metrics metric USING match_players player "
            "WHERE player.id = metric.match_player_id AND player.match_id = %s",
            (match_id,),
        )
        connection.execute("DELETE FROM team_match_metrics WHERE match_id = %s", (match_id,))
        if frames is not None:
            connection.execute(
                "INSERT INTO jobs (kind, payload) VALUES ('analyze', %s)",
                (Jsonb({"match_id": str(match_id)}),),
            )
        _refresh_identities(connection, match_id)
    if frames is None:
        log.warning(
            "match %s parsed again from build %s: %s", match_id, header["game_build"], error_code
        )
    else:
        log.info("match %s parsed again with parser %s", match_id, header["parser_version"])
