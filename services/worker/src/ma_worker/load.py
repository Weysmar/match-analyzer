"""Writes what the parser found into the database."""

import logging
import uuid
from datetime import UTC, datetime

from ma_schemas import HeaderDocument
from ma_worker.queue import Connection

log = logging.getLogger("ma_worker")


def played_at_utc(header: HeaderDocument) -> datetime | None:
    """A replay's `Date` has no time zone: it is stored as if it were UTC, and `played_at_source`
    says so. It only serves to sort a player's matches."""
    value = header["played_at"]
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def existing_match(connection: Connection, key: str) -> tuple[uuid.UUID, str | None] | None:
    row = connection.execute(
        "SELECT id, raw_key FROM matches WHERE dedupe_key = %s", (key,)
    ).fetchone()
    return None if row is None else (row[0], row[1])


def insert_match(
    connection: Connection, header: HeaderDocument, key: str, raw_key: str
) -> uuid.UUID | None:
    """The new match, or None when another worker has just created the same one."""
    version = header["replay_version"]
    row = connection.execute(
        """
        INSERT INTO matches (
            dedupe_key, match_guid, status, game_build, build_id, changelist, replay_major,
            replay_minor, replay_net, map, played_at, played_at_source, duration_s, match_type,
            playlist, team_size, score_blue, score_orange, raw_key, parser_version, parsed_at
        )
        VALUES (
            %s, %s, 'header_only', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, now()
        )
        ON CONFLICT (dedupe_key) DO NOTHING
        RETURNING id
        """,
        (
            key,
            header["match_guid"],
            header["game_build"],
            header["build_id"],
            header["changelist"],
            version["major"],
            version["minor"],
            version["net"],
            header["map"],
            played_at_utc(header),
            header["played_at_source"],
            header["duration_s"],
            header["match_type"],
            header["playlist"],
            header["team_size"],
            header["score"]["blue"],
            header["score"]["orange"],
            raw_key,
            header["parser_version"],
        ),
    ).fetchone()
    if row is None:
        return None
    match_id: uuid.UUID = row[0]
    _warn_about_a_shared_guid(connection, header, key, match_id)
    _insert_players_and_goals(connection, header, match_id)
    return match_id


def _warn_about_a_shared_guid(
    connection: Connection, header: HeaderDocument, key: str, match_id: uuid.UUID
) -> None:
    """Same `MatchGUID`, other players or score: kept apart, and worth a look (I10). It may be a
    forged file, or a header that differs between clients."""
    if header["match_guid"] is None:
        return
    other = connection.execute(
        "SELECT 1 FROM matches WHERE match_guid = %s AND dedupe_key <> %s LIMIT 1",
        (header["match_guid"], key),
    ).fetchone()
    if other is not None:
        log.warning("match %s shares its guid with a match of different content", match_id)


def _insert_players_and_goals(
    connection: Connection, header: HeaderDocument, match_id: uuid.UUID
) -> None:
    by_name: dict[str, int] = {}
    for player in header["players"]:
        # The table needs a team. None of the corpus lacks one, but the format allows it.
        if player["team"] is None:
            continue
        row = connection.execute(
            """
            INSERT INTO match_players (
                match_id, platform, platform_id, display_name, team, score, goals, assists, saves,
                shots, is_bot
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                match_id,
                player["platform"],
                player["platform_id"],
                player["name"],
                player["team"],
                player["score"],
                player["goals"],
                player["assists"],
                player["saves"],
                player["shots"],
                player["is_bot"],
            ),
        ).fetchone()
        assert row is not None
        by_name.setdefault(player["name"], row[0])
    for goal in header["goals"]:
        if goal["time_s"] is None:
            continue
        name = goal["player_name"]
        connection.execute(
            "INSERT INTO match_events (match_id, kind, frame, time_s, team, actor_player_id) "
            "VALUES (%s, 'goal', %s, %s, %s, %s)",
            (
                match_id,
                goal["frame"],
                goal["time_s"],
                goal["team"],
                None if name is None else by_name.get(name),
            ),
        )
