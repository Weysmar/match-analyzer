"""Rotation roles (T14.1 of docs/PLAN-V2.md): first, second and third man, in 2v2 and 3v3.

The roles are subtr-actor 1.5.1's (`RotationCalculator`, stats/calculators/rotation.rs), our
reference for this continuous measure:

- the first man is the team's player closest to the ball, on the ground plane, but only when the
  next one is more than `thresholds.FIRST_MAN_MARGIN` further: otherwise who goes is ambiguous;
- a new first man only takes the role after holding it `thresholds.FIRST_MAN_DEBOUNCE`, so that two
  players swapping for an instant do not flicker;
- the others follow by distance to the ball: second man, then third.

Roles exist in live play only, and only while the whole team is on the field: a teammate away or
demolished leaves nobody's role known. A role share is over the time the player had a role, so the
three add up to 100 %; the ambiguous time stays out (7 to 13 % of live play on a sample match).
A 1v1 has no roles, and a 2v2 no third man: those metrics are None.
"""

import math
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum
from itertools import groupby

from rl_analysis.constants import Phase
from rl_analysis.frames import PerPlayer
from rl_analysis.match import Match
from rl_analysis.thresholds import FIRST_MAN_DEBOUNCE, FIRST_MAN_MARGIN


class Role(Enum):
    FIRST = "first"
    SECOND = "second"
    THIRD = "third"
    AMBIGUOUS = "ambiguous"


_BY_RANK = (Role.SECOND, Role.THIRD)


@dataclass
class _FirstMan:
    """A team's first man, debounced: subtr-actor's `TeamFirstManTracker`."""

    stable: int | None = None
    pending: int | None = None
    pending_s: float = 0.0

    def reset(self) -> None:
        self.stable, self.pending, self.pending_s = None, None, 0.0

    def update(self, raw: int | None, dt_s: float) -> None:
        if raw is None:
            self.pending, self.pending_s = None, 0.0
        elif self.stable is None or self.stable == raw:
            self.stable, self.pending, self.pending_s = raw, None, 0.0
        else:
            self.pending_s = self.pending_s + dt_s if self.pending == raw else dt_s
            self.pending = raw
            if self.pending_s >= FIRST_MAN_DEBOUNCE.value:
                self.stable, self.pending, self.pending_s = raw, None, 0.0


@dataclass
class Roles:
    """Seconds of live play each player spent in each role, and, at each moment asked for, the roles
    of the last frame at or before it (empty out of live play)."""

    seconds: dict[int, dict[Role, float]] = field(
        default_factory=lambda: defaultdict(lambda: dict.fromkeys(Role, 0.0))
    )
    at: dict[float, dict[int, Role]] = field(default_factory=dict)


def assign(distances: dict[int, float], tracker: _FirstMan, dt_s: float) -> dict[int, Role]:
    """One frame of one team: each player's role, from their distance to the ball."""
    ranked = sorted(distances, key=lambda player: (distances[player], player))
    first, second = ranked[0], ranked[1]
    raw = first if distances[second] - distances[first] > FIRST_MAN_MARGIN.value else None
    tracker.update(raw, dt_s)
    if raw is None or tracker.stable is None:
        return dict.fromkeys(ranked, Role.AMBIGUOUS)
    roles = {tracker.stable: Role.FIRST}
    others = [player for player in ranked if player != tracker.stable]
    for rank, player in enumerate(others):
        roles[player] = _BY_RANK[rank] if rank < len(_BY_RANK) else Role.AMBIGUOUS
    return roles


_COLUMNS = (
    "frame", "dt_s", "phase", "ball_x", "ball_y", "player_idx", "team", "present", "demolished",
    "x", "y", "time_s",
)  # fmt: skip


def resolve(match: Match, at: Iterable[float] = ()) -> Roles:
    """Each player's time in each role, frame by frame, weighted by `dt_s`, and the roles at each
    moment of `at`. One pass over the rows in plain Python: a polars filter per frame and team would
    cost seconds a match."""
    rows = match.frames.select(_COLUMNS).sort("frame", "player_idx").iter_rows()
    trackers = {0: _FirstMan(), 1: _FirstMan()}
    roles = Roles()
    moments = sorted(set(at))
    latest: dict[int, Role] = {}
    for _, grouped in groupby(rows, key=lambda row: row[0]):
        players = list(grouped)
        _, dt_s, phase, ball_x, ball_y = players[0][:5]
        while moments and moments[0] < players[0][11]:
            roles.at[moments.pop(0)] = dict(latest)
        if dt_s <= 0:
            continue
        latest = {}
        if phase != Phase.ACTIVE or ball_x is None or ball_y is None:
            for tracker in trackers.values():
                tracker.reset()
            continue
        for team, tracker in trackers.items():
            members = [row for row in players if row[6] == team]
            on_field = [row for row in members if row[7] and not row[8] and row[9] is not None]
            if not 2 <= len(members) <= 3 or len(on_field) != len(members):
                tracker.reset()
                continue
            distances = {
                int(row[5]): math.hypot(row[9] - ball_x, row[10] - ball_y) for row in on_field
            }
            for player, role in assign(distances, tracker, float(dt_s)).items():
                roles.seconds[player][role] += float(dt_s)
                latest[player] = role
    for moment in moments:
        roles.at[moment] = dict(latest)
    return roles


def _team_sizes(match: Match) -> dict[int, int]:
    sizes: dict[int, int] = defaultdict(int)
    for member in match.events["roster"]:
        sizes[member["team"]] += 1
    return {member["player_idx"]: sizes[member["team"]] for member in match.events["roster"]}


def _share(match: Match, role: Role, *, needs: int = 2) -> PerPlayer:
    resolved = resolve(match)
    sizes = _team_sizes(match)
    shares: PerPlayer = {}
    for player in match.players:
        spent = resolved.seconds.get(player)
        with_role = sum(spent[r] for r in (Role.FIRST, Role.SECOND, Role.THIRD)) if spent else 0.0
        # A team smaller than the role needs has none of it, unless the frames say otherwise: a
        # private match where someone switched teams.
        too_small = sizes.get(player, 0) < needs and not (spent and spent[role] > 0)
        if too_small or not spent or with_role <= 0:
            shares[player] = None
        else:
            shares[player] = 100.0 * spent[role] / with_role
    return shares


def first_share(match: Match) -> PerPlayer:
    """`rot.pct_first`: share of the player's time with a role spent as first man, the closest to
    the ball by more than 250 uu, debounced 0.35 s. In %; None in 1v1."""
    return _share(match, Role.FIRST)


def second_share(match: Match) -> PerPlayer:
    """`rot.pct_second`: share of the player's time with a role spent as second man, the next
    closest to the ball after the first. In %; None in 1v1."""
    return _share(match, Role.SECOND)


def third_share(match: Match) -> PerPlayer:
    """`rot.pct_third`: share of the player's time with a role spent as third man, the furthest
    from the ball, in 3v3. In %; None in 1v1 and 2v2."""
    return _share(match, Role.THIRD, needs=3)
