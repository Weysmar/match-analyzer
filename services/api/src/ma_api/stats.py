"""A player's own numbers, over their last matches.

Only matches where the player is known and which have metrics count: a `header_only` match has none,
and would otherwise take a place among the last N without saying anything. Each match weighs the
same, whatever it lasted: the average answers "over my last 20 matches".
"""

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query
from psycopg import sql

from ma_api import models, sessions
from ma_api.db import ConnectionDep
from ma_api.errors import ApiError
from ma_api.owner import Owner
from ma_api.sessions import IdentityDep

_LAST_MAX = 200

# The metrics rl_analysis computes: V1 (docs/PLAN.md, step 7), then V2. A test keeps them equal.
METRIC_IDS = frozenset(
    {
        "boost.used_per_min",
        "boost.avg",
        "boost.pct_zero",
        "boost.pct_full",
        "boost.pads_big",
        "boost.pads_small",
        "boost.pads_enemy_half",
        "move.speed_avg",
        "move.pct_supersonic",
        "move.pct_ground",
        "move.pct_low_air",
        "move.pct_high_air",
        "pos.pct_def_third",
        "pos.pct_mid_third",
        "pos.pct_att_third",
        "pos.pct_ahead_ball",
        "pos.pct_behind_ball",
        "pos.dist_ball_avg",
        "pos.pct_last_back",
        "event.demos_inflicted",
        "event.demos_taken",
        # V2 (docs/PLAN-V2.md, T11.4).
        "touch.count",
        "touch.per_min",
        "touch.pct_aerial",
        "touch.pct_hard",
        # T11.6.
        "poss.player_pct",
        "poss.turnovers_lost",
        "poss.turnovers_won",
    }
)

# The team metrics, shown on the match sheet only (T11.5).
TEAM_METRIC_IDS = frozenset({"poss.team_pct"})

Last = Annotated[int, Query(ge=1, le=_LAST_MAX)]
Scope = Literal["all", "verified"]


def _recent(owner: Owner, scope: Scope, last: int) -> sql.Composed:
    """The common table of both routes: the owner's last matches that can be counted."""
    verified = sql.SQL("AND link.verified") if scope == "verified" else sql.SQL("")
    return sql.SQL(
        """
        WITH recent AS (
            SELECT link.match_id, link.match_player_id, link.verified, match.played_at,
                   coalesce(match.played_at, match.created_at) AS sort_at
            FROM user_matches link
            JOIN matches match ON match.id = link.match_id
            WHERE {owner} {verified} AND EXISTS (
                SELECT FROM player_match_metrics metric
                WHERE metric.match_player_id = link.match_player_id
            )
            ORDER BY sort_at DESC, match.id DESC
            LIMIT {last}
        )
        """
    ).format(owner=owner.condition, verified=verified, last=sql.Literal(last))


router = APIRouter()


@router.get("/stats/me", response_model=models.Stats)
def my_stats(
    connection: ConnectionDep, identity: IdentityDep, last: Last = 20, scope: Scope = "all"
) -> dict[str, Any]:
    owner = sessions.require_owner(identity)
    recent = _recent(owner, scope, last)
    counts = connection.execute(
        recent + sql.SQL("SELECT count(*), count(*) FILTER (WHERE verified) FROM recent")
    ).fetchone()
    assert counts is not None
    averages = connection.execute(
        recent
        + sql.SQL(
            """
            SELECT metric.metric_id, avg(metric.value)
            FROM recent
            JOIN player_match_metrics metric USING (match_player_id)
            GROUP BY metric.metric_id
            """
        )
    ).fetchall()
    return {
        "matches_count": counts[0],
        "verified_count": counts[1],
        # Null when undefined in every match, like the last back in 1v1.
        "averages": {row[0]: row[1] for row in averages},
    }


@router.get("/stats/me/history", response_model=models.History)
def my_history(
    metric_id: str,
    connection: ConnectionDep,
    identity: IdentityDep,
    last: Last = 20,
    scope: Scope = "all",
) -> dict[str, Any]:
    """One metric over time, oldest first."""
    owner = sessions.require_owner(identity)
    if metric_id not in METRIC_IDS:
        raise ApiError(422, "unknown_metric")
    rows = connection.execute(
        _recent(owner, scope, last)
        + sql.SQL(
            """
            SELECT recent.match_id, recent.played_at, metric.value, recent.verified
            FROM recent
            JOIN player_match_metrics metric USING (match_player_id)
            WHERE metric.metric_id = {}
            ORDER BY recent.sort_at, recent.match_id
            """
        ).format(sql.Literal(metric_id))
    ).fetchall()
    return {
        "metric_id": metric_id,
        "points": [
            {
                "match_id": str(row[0]),
                "played_at": None if row[1] is None else row[1].isoformat(),
                "value": row[2],
                "verified": row[3],
            }
            for row in rows
        ],
    }
