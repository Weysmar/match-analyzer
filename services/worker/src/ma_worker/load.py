"""Writes what the parser found into the database."""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from ma_schemas import EventsDocument, HeaderDocument
from ma_worker.queue import Connection

log = logging.getLogger("ma_worker")

# Any fixed value: it only has to give every match key one lasting identifier.
_MATCH_NAMESPACE = uuid.UUID("6f1c2f9e-3b5d-4f0a-9a57-2d5e8c1b7a40")


def match_id_for(key: str) -> uuid.UUID:
    """The same match always gets the same id. Its files are stored under this id before the
    transaction, so a job taken up again writes over them instead of leaving orphans behind."""
    return uuid.uuid5(_MATCH_NAMESPACE, key)


@dataclass(frozen=True)
class Frames:
    """What the network stream gave, once its files are stored."""

    events: EventsDocument
    frames_key: str
    events_key: str


@dataclass(frozen=True)
class PlayerRow:
    frames_idx: int | None
    platform: str
    platform_id: str | None
    name: str
    team: int
    score: int | None
    goals: int | None
    assists: int | None
    saves: int | None
    shots: int | None
    is_bot: bool
    anonymized: bool


def played_at_utc(header: HeaderDocument) -> datetime | None:
    """A replay's `Date` has no time zone: it is stored as if it were UTC, and `played_at_source`
    says so. It only serves to sort a player's matches."""
    value = header["played_at"]
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def merge_players(header: HeaderDocument, events: EventsDocument | None) -> list[PlayerRow]:
    """The players of a match. The roster comes from the network stream and is complete, and it
    holds the name to show; the header holds the end-of-match numbers. Without a roster, the header
    is all there is, real names included (D20), until the match is parsed again."""
    remaining = [player for player in header["players"] if player["team"] is not None]
    rows: list[PlayerRow] = []
    unmatched_anonymous = False
    for member in events["roster"] if events is not None else []:
        found = next(
            (
                player
                for player in remaining
                if player["platform"] == member["platform"]
                and player["platform_id"] is not None
                and player["platform_id"] == member["platform_id"]
            ),
            None,
        )
        if found is None:
            # An old replay holds no id for Epic players in its header: only the name is left.
            found = next(
                (
                    player
                    for player in remaining
                    if player["platform_id"] is None
                    and player["name"] == member["name"]
                    and player["team"] == member["team"]
                ),
                None,
            )
        if found is not None:
            remaining.remove(found)
        elif member["anonymized"]:
            unmatched_anonymous = True
        rows.append(
            PlayerRow(
                frames_idx=member["player_idx"],
                platform=member["platform"],
                platform_id=member["platform_id"]
                or (found["platform_id"] if found is not None else None),
                name=member["name"],
                team=member["team"],
                score=found["score"] if found is not None else None,
                goals=found["goals"] if found is not None else None,
                assists=found["assists"] if found is not None else None,
                saves=found["saves"] if found is not None else None,
                shots=found["shots"] if found is not None else None,
                is_bot=member["platform"] == "bot" or (found is not None and found["is_bot"]),
                anonymized=member["anonymized"],
            )
        )
    # What the header alone knows: someone who left, say. But a player who asked for anonymity could
    # not be recognized by name, and one of these lines may well hold their real one.
    if unmatched_anonymous:
        remaining = []
    for player in remaining:
        assert player["team"] is not None
        rows.append(
            PlayerRow(
                frames_idx=None,
                platform=player["platform"],
                platform_id=player["platform_id"],
                name=player["name"],
                team=player["team"],
                score=player["score"],
                goals=player["goals"],
                assists=player["assists"],
                saves=player["saves"],
                shots=player["shots"],
                is_bot=player["is_bot"],
                anonymized=False,
            )
        )
    return rows


def existing_match(connection: Connection, key: str) -> tuple[uuid.UUID, str | None] | None:
    row = connection.execute(
        "SELECT id, raw_key FROM matches WHERE dedupe_key = %s", (key,)
    ).fetchone()
    return None if row is None else (row[0], row[1])


def insert_match(
    connection: Connection,
    match_id: uuid.UUID,
    header: HeaderDocument,
    key: str,
    raw_key: str,
    frames: Frames | None,
    error_code: str | None,
) -> bool:
    """False when another worker has just created the same match."""
    version = header["replay_version"]
    events = None if frames is None else frames.events
    playlist = header["playlist"]
    if playlist is None and events is not None and events["playlist_id"] is not None:
        playlist = str(events["playlist_id"])
    duration = header["duration_s"]
    if duration is None and events is not None:
        duration = events["duration_s"]
    row = connection.execute(
        """
        INSERT INTO matches (
            id, dedupe_key, match_guid, status, game_build, build_id, changelist, replay_major,
            replay_minor, replay_net, map, played_at, played_at_source, duration_s, match_type,
            playlist, team_size, score_blue, score_orange, arena_out_of_bounds, raw_key,
            frames_key, events_key, parser_version, error_code, parsed_at
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, now()
        )
        ON CONFLICT (dedupe_key) DO NOTHING
        RETURNING id
        """,
        (
            match_id,
            key,
            header["match_guid"],
            "parsed" if frames is not None else "header_only",
            header["game_build"],
            header["build_id"],
            header["changelist"],
            version["major"],
            version["minor"],
            version["net"],
            header["map"],
            played_at_utc(header),
            header["played_at_source"],
            duration,
            header["match_type"],
            playlist,
            header["team_size"],
            header["score"]["blue"],
            header["score"]["orange"],
            events["arena_out_of_bounds"] if events is not None else False,
            raw_key,
            None if frames is None else frames.frames_key,
            None if frames is None else frames.events_key,
            header["parser_version"],
            error_code,
        ),
    ).fetchone()
    if row is None:
        return False
    _warn_about_a_shared_guid(connection, header, key, match_id)
    ids = _insert_players(connection, match_id, merge_players(header, events))
    if events is None:
        _insert_header_goals(connection, match_id, header, ids)
    else:
        _insert_events(connection, match_id, events, ids)
    return True


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


def _insert_players(
    connection: Connection, match_id: uuid.UUID, players: list[PlayerRow]
) -> dict[PlayerRow, int]:
    ids: dict[PlayerRow, int] = {}
    for player in players:
        row = connection.execute(
            """
            INSERT INTO match_players (
                match_id, frames_idx, platform, platform_id, display_name, team, score, goals,
                assists, saves, shots, is_bot, anonymized
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                match_id,
                player.frames_idx,
                player.platform,
                player.platform_id,
                player.name,
                player.team,
                player.score,
                player.goals,
                player.assists,
                player.saves,
                player.shots,
                player.is_bot,
                player.anonymized,
            ),
        ).fetchone()
        assert row is not None
        ids[player] = row[0]
    return ids


def _insert_header_goals(
    connection: Connection,
    match_id: uuid.UUID,
    header: HeaderDocument,
    ids: dict[PlayerRow, int],
) -> None:
    by_name: dict[str, int] = {}
    for player, player_id in ids.items():
        by_name.setdefault(player.name, player_id)
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


def _insert_events(
    connection: Connection,
    match_id: uuid.UUID,
    events: EventsDocument,
    ids: dict[PlayerRow, int],
) -> None:
    """Goals and demolitions, for the match sheet and the metrics. Pads and the rest stay in the
    object store: only the analysis needs them."""
    by_index = {player.frames_idx: (player_id, player) for player, player_id in ids.items()}

    def player_id_of(index: int | None) -> int | None:
        found = by_index.get(index)
        return None if found is None else found[0]

    for goal in events["goals"]:
        connection.execute(
            "INSERT INTO match_events (match_id, kind, frame, time_s, team, actor_player_id) "
            "VALUES (%s, 'goal', %s, %s, %s, %s)",
            (
                match_id,
                goal["frame"],
                goal["time_s"],
                goal["team"],
                player_id_of(goal["player_idx"]),
            ),
        )
    for demolition in events["demolitions"]:
        attacker = by_index.get(demolition["attacker_idx"])
        connection.execute(
            "INSERT INTO match_events (match_id, kind, frame, time_s, team, actor_player_id, "
            "victim_player_id) VALUES (%s, 'demolition', %s, %s, %s, %s, %s)",
            (
                match_id,
                demolition["frame"],
                demolition["time_s"],
                None if attacker is None else attacker[1].team,
                None if attacker is None else attacker[0],
                player_id_of(demolition["victim_idx"]),
            ),
        )
