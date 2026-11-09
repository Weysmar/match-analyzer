"""Matches, as their owner sees them.

Section 11 of CLAUDE.md: other players appear by their name in the match of the one who brought it,
and nowhere else. Columns are always listed by hand, so that `platform_id` can never come along.
"""

import uuid
from collections import defaultdict
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query
from psycopg import sql
from psycopg.rows import dict_row
from pydantic import BaseModel

from ma_api import attach, models, pagination, sessions
from ma_api.db import Connection, ConnectionDep
from ma_api.errors import ApiError
from ma_api.owner import Owner, owned_match
from ma_api.sessions import IdentityDep

_LIST_MAX = 200
# Bots and unknown platforms have nothing to remember a player by.
_CLAIMABLE = {"steam", "epic", "psn", "xbox", "switch"}


def _score(row: dict[str, Any]) -> dict[str, int | None]:
    return {"blue": row["score_blue"], "orange": row["score_orange"]}


def _won(row: dict[str, Any], team: int | None) -> bool | None:
    """Unknown as long as the player or the score is."""
    blue, orange = row["score_blue"], row["score_orange"]
    if team is None or blue is None or orange is None:
        return None
    return bool(blue > orange) if team == 0 else bool(orange > blue)


def _iso(value: Any) -> str | None:
    return None if value is None else value.isoformat()


router = APIRouter()


@router.get("/matches", response_model=models.MatchPage)
def list_matches(
    connection: ConnectionDep,
    identity: IdentityDep,
    scope: Literal["all", "verified"] = "all",
    limit: Annotated[int, Query(ge=1, le=_LIST_MAX)] = 50,
    cursor: str | None = None,
) -> dict[str, Any]:
    """The owner's matches, last played first. A match without a date goes by its arrival."""
    owner = sessions.require_owner(identity)
    conditions: list[sql.Composable] = [owner.condition]
    if scope == "verified":
        conditions.append(sql.SQL("link.verified"))
    if cursor is not None:
        played_at, match_id = pagination.decode(cursor)
        conditions.append(
            sql.SQL("(coalesce(match.played_at, match.created_at), match.id) < ({}, {})").format(
                sql.Literal(played_at), sql.Literal(match_id)
            )
        )
    query = sql.SQL(
        """
        SELECT match.id, match.played_at, match.map, match.playlist, match.team_size,
               match.score_blue, match.score_orange, match.status, link.verified, player.team,
               coalesce(match.played_at, match.created_at) AS sort_at
        FROM user_matches link
        JOIN matches match ON match.id = link.match_id
        LEFT JOIN match_players player ON player.id = link.match_player_id
        WHERE {}
        ORDER BY sort_at DESC, match.id DESC
        LIMIT {}
        """
    ).format(sql.SQL(" AND ").join(conditions), sql.Literal(limit + 1))
    with connection.cursor(row_factory=dict_row) as rows:
        found = rows.execute(query).fetchall()
    page = found[:limit]
    more = len(found) > limit
    return {
        "items": [
            {
                "match_id": str(row["id"]),
                "played_at": _iso(row["played_at"]),
                "map": row["map"],
                "playlist": row["playlist"],
                "team_size": row["team_size"],
                "score": _score(row),
                "status": row["status"],
                "verified": row["verified"],
                "my_team": row["team"],
                "won": _won(row, row["team"]),
            }
            for row in page
        ],
        "next_cursor": pagination.encode(page[-1]["sort_at"], page[-1]["id"]) if more else None,
    }


def _match_row(connection: Connection, match_id: uuid.UUID) -> dict[str, Any]:
    with connection.cursor(row_factory=dict_row) as rows:
        row = rows.execute(
            """
            SELECT id, played_at, map, match_type, playlist, team_size, duration_s, score_blue,
                   score_orange, status, arena_out_of_bounds, game_length_s, overtime_from_s
            FROM matches WHERE id = %s
            """,
            (match_id,),
        ).fetchone()
    assert row is not None  # A link holds a foreign key to its match.
    return row


def _players(connection: Connection, match_id: uuid.UUID) -> list[dict[str, Any]]:
    with connection.cursor(row_factory=dict_row) as rows:
        return rows.execute(
            """
            SELECT id, display_name, team, score, goals, assists, saves, shots, is_bot
            FROM match_players WHERE match_id = %s ORDER BY team, score DESC NULLS LAST, id
            """,
            (match_id,),
        ).fetchall()


def _goals(connection: Connection, match_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT event.time_s, event.team, player.display_name, event.game_time_s
        FROM match_events event
        LEFT JOIN match_players player ON player.id = event.actor_player_id
        WHERE event.match_id = %s AND event.kind = 'goal'
        ORDER BY event.time_s, event.id
        """,
        (match_id,),
    ).fetchall()
    return [
        {"time_s": row[0], "team": row[1], "player_name": row[2], "game_time_s": row[3]}
        for row in rows
    ]


def _metrics(connection: Connection, match_id: uuid.UUID) -> dict[str, dict[str, float | None]]:
    rows = connection.execute(
        """
        SELECT metric.match_player_id, metric.metric_id, metric.value
        FROM player_match_metrics metric
        JOIN match_players player ON player.id = metric.match_player_id
        WHERE player.match_id = %s
        """,
        (match_id,),
    ).fetchall()
    metrics: dict[str, dict[str, float | None]] = defaultdict(dict)
    for player_id, metric_id, value in rows:
        metrics[str(player_id)][metric_id] = value
    return dict(metrics)


def _team_metrics(
    connection: Connection, match_id: uuid.UUID
) -> dict[str, dict[str, float | None]]:
    """By team number, as a string: `{"0": {...}, "1": {...}}` (annex G of docs/PLAN-V2.md)."""
    rows = connection.execute(
        "SELECT team, metric_id, value FROM team_match_metrics WHERE match_id = %s",
        (match_id,),
    ).fetchall()
    metrics: dict[str, dict[str, float | None]] = defaultdict(dict)
    for team, metric_id, value in rows:
        metrics[str(team)][metric_id] = value
    return dict(metrics)


@router.get("/matches/{match_id}", response_model=models.MatchSheet)
def get_match(
    match_id: uuid.UUID, connection: ConnectionDep, identity: IdentityDep
) -> dict[str, Any]:
    owner = sessions.require_owner(identity)
    link = owned_match(connection, owner, match_id)
    match = _match_row(connection, match_id)
    players = _players(connection, match_id)
    return {
        "match": {
            "match_id": str(match["id"]),
            "played_at": _iso(match["played_at"]),
            "map": match["map"],
            "match_type": match["match_type"],
            "playlist": match["playlist"],
            "team_size": match["team_size"],
            "duration_s": match["duration_s"],
            "score": _score(match),
            "status": match["status"],
            "arena_out_of_bounds": match["arena_out_of_bounds"],
            "game_length_s": match["game_length_s"],
            "overtime_from_s": match["overtime_from_s"],
        },
        "players": [
            {
                "match_player_id": player["id"],
                "name": player["display_name"],
                "team": player["team"],
                "score": player["score"],
                "goals": player["goals"],
                "assists": player["assists"],
                "saves": player["saves"],
                "shots": player["shots"],
                "is_bot": player["is_bot"],
                "is_me": player["id"] == link["match_player_id"],
            }
            for player in players
        ],
        "goals": _goals(connection, match_id),
        "metrics": _metrics(connection, match_id),
        "team_metrics": _team_metrics(connection, match_id),
        "me": {
            "match_player_id": link["match_player_id"],
            "verified": link["verified"],
            "identity_source": link["identity_source"],
        },
        "needs_identity": link["identity_source"] == "none"
        and any(not player["is_bot"] for player in players),
    }


class IdentityIn(BaseModel):
    match_player_id: int


def _forget(connection: Connection, owner: Owner, player_id: int) -> None:
    """A wrong choice must not stick: the matches it reached go back to having no identity."""
    row = connection.execute(
        "SELECT platform, platform_id FROM match_players WHERE id = %s", (player_id,)
    ).fetchone()
    assert row is not None
    platform, platform_id = row
    if platform_id is None:
        return
    connection.execute(
        sql.SQL("DELETE FROM player_claims WHERE platform = %s AND platform_id = %s AND {}").format(
            owner.condition
        ),
        (platform, platform_id),
    )
    connection.execute(
        sql.SQL(
            """
            UPDATE user_matches SET match_player_id = NULL, identity_source = 'none'
            WHERE identity_source = 'memorized' AND {} AND match_player_id IN (
                SELECT id FROM match_players WHERE platform = %s AND platform_id = %s
            )
            """
        ).format(owner.condition),
        (platform, platform_id),
    )


def _memorize(connection: Connection, owner: Owner, platform: str, platform_id: str) -> None:
    connection.execute(
        "INSERT INTO player_claims (user_id, anonymous_session_id, platform, platform_id) "
        "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
        (owner.user_id, owner.anonymous_session_id, platform, platform_id),
    )
    attach.apply_claims(connection, owner)


@router.post("/matches/{match_id}/identity", response_model=models.IdentityChosen)
def choose_identity(
    match_id: uuid.UUID,
    choice: IdentityIn,
    connection: ConnectionDep,
    identity: IdentityDep,
) -> dict[str, Any]:
    """ "Which of these players are you?" A choice never verifies a match: only a linked account
    whose id this player carries does, which the last step checks."""
    owner = sessions.require_owner(identity)
    link = owned_match(connection, owner, match_id)
    if link["verified"]:
        raise ApiError(409, "identity_locked")
    player = connection.execute(
        "SELECT platform, platform_id, is_bot FROM match_players WHERE id = %s AND match_id = %s",
        (choice.match_player_id, match_id),
    ).fetchone()
    if player is None or player[2]:
        raise ApiError(422, "not_a_player")
    platform, platform_id, _ = player

    previous = link["match_player_id"]
    if previous is not None and previous != choice.match_player_id:
        _forget(connection, owner, previous)
    connection.execute(
        "UPDATE user_matches SET match_player_id = %s, identity_source = 'claimed' WHERE id = %s",
        (choice.match_player_id, link["id"]),
    )
    if platform in _CLAIMABLE and platform_id is not None:
        _memorize(connection, owner, platform, platform_id)
    if owner.user_id is not None:
        attach.refresh_verification(connection, owner.user_id)
        link = owned_match(connection, owner, match_id)
    return {"verified": link["verified"], "identity_source": link["identity_source"]}
