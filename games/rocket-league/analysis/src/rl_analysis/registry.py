"""The metrics, each with its id and unit: the V1 ones (section 8.2 of CLAUDE.md, step 7 of
docs/PLAN.md), then the V2 ones (docs/PLAN-V2.md, section 5). Adding one needs no migration:
`player_match_metrics` holds a row per player and metric, `team_match_metrics` per team and
metric for the team ones."""

from collections.abc import Callable
from dataclasses import dataclass

from rl_analysis import boost, kickoffs, movement, positioning, possession, touches
from rl_analysis.frames import PerPlayer
from rl_analysis.match import Match
from rl_analysis.possession import TEAMS, PerTeam


@dataclass(frozen=True)
class Metric:
    id: str
    unit: str
    compute: Callable[[Match], PerPlayer]

    @property
    def definition(self) -> str:
        """The written definition, which lives in the computing function's docstring."""
        return (self.compute.__doc__ or "").strip()


METRICS: tuple[Metric, ...] = (
    Metric("boost.used_per_min", "%/min", boost.used_per_minute),
    Metric("boost.avg", "%", boost.average),
    Metric("boost.pct_zero", "%", boost.time_empty),
    Metric("boost.pct_full", "%", boost.time_full),
    Metric("boost.pads_big", "count", boost.pads_big),
    Metric("boost.pads_small", "count", boost.pads_small),
    Metric("boost.pads_enemy_half", "count", boost.pads_enemy_half),
    Metric("move.speed_avg", "uu/s", movement.speed_average),
    Metric("move.pct_supersonic", "%", movement.time_supersonic),
    Metric("move.pct_ground", "%", movement.time_on_ground),
    Metric("move.pct_low_air", "%", movement.time_in_low_air),
    Metric("move.pct_high_air", "%", movement.time_in_high_air),
    Metric("pos.pct_def_third", "%", positioning.defensive_third),
    Metric("pos.pct_mid_third", "%", positioning.middle_third),
    Metric("pos.pct_att_third", "%", positioning.attacking_third),
    Metric("pos.pct_ahead_ball", "%", positioning.ahead_of_ball),
    Metric("pos.pct_behind_ball", "%", positioning.behind_ball),
    Metric("pos.dist_ball_avg", "uu", positioning.distance_to_ball),
    Metric("pos.pct_last_back", "%", positioning.last_back),
    Metric("event.demos_inflicted", "count", positioning.demolitions_inflicted),
    Metric("event.demos_taken", "count", positioning.demolitions_taken),
    Metric("touch.count", "count", touches.count),
    Metric("touch.per_min", "/min", touches.per_minute),
    Metric("touch.pct_aerial", "%", touches.share_aerial),
    Metric("touch.pct_hard", "%", touches.share_hard),
    Metric("poss.player_pct", "%", possession.player_share),
    Metric("poss.turnovers_lost", "count", possession.turnovers_lost),
    Metric("poss.turnovers_won", "count", possession.turnovers_won),
    Metric("kick.taken", "count", kickoffs.taken),
    Metric("kick.won_pct", "%", kickoffs.won_share),
    Metric("kick.time_to_ball", "s", kickoffs.time_to_ball),
)


@dataclass(frozen=True)
class TeamMetric:
    """A metric of a team rather than of a player (marked *(équipe)* in docs/PLAN-V2.md)."""

    id: str
    unit: str
    compute: Callable[[Match], PerTeam]

    @property
    def definition(self) -> str:
        return (self.compute.__doc__ or "").strip()


TEAM_METRICS: tuple[TeamMetric, ...] = (
    TeamMetric("poss.team_pct", "%", possession.team_share),
    TeamMetric("kick.goals_conceded", "count", kickoffs.goals_conceded),
)


def compute(match: Match) -> dict[int, dict[str, float | None]]:
    """Every metric for every player of the roster, by `player_idx`. A player with no frame gets
    None for a measure of time, and 0 for a count."""
    results: dict[int, dict[str, float | None]] = {player: {} for player in match.players}
    for metric in METRICS:
        values = metric.compute(match)
        for player in match.players:
            results[player][metric.id] = values.get(player)
    return results


def compute_teams(match: Match) -> dict[int, dict[str, float | None]]:
    """Every team metric for both teams, by team number."""
    results: dict[int, dict[str, float | None]] = {team: {} for team in TEAMS}
    for metric in TEAM_METRICS:
        values = metric.compute(match)
        for team in TEAMS:
            results[team][metric.id] = values.get(team)
    return results
