"""Ball possession (T11.5 and T11.6 of docs/PLAN-V2.md), resolved from the touches.

The resolution is subtr-actor 1.5.1's (`PossessionResolver`, stats/calculators/possession.rs), our
reference for this continuous measure (section 4, rule 4):

- a single touch on a loose ball grants nothing: the team must touch it again within the window
  (`thresholds.POSSESSION_WINDOW`), and is then credited from its first touch;
- a team keeps the ball while its touches come within the window. With no follow-up, its possession
  ends at its last touch, and the time after is neutral;
- an opponent's touch only challenges the holder. It becomes a turnover once the opponent touches
  again within the window (or both teams touch at once): the holder is credited up to its last
  touch, the gap is neutral, and the new holder from its first touch. A holder who touches the ball
  back has repelled the challenge, and keeps its possession;
- both teams touching at once on a loose ball leaves it loose.

Only live play counts (the `active` phase, subtr-actor's live play): each stretch starts neutral,
and a possession still open when it ends stops at its last touch.

A match without detected touches (parsed before rl-parse 0.2.0) has no possession: every metric of
this module is then None, never 0.
"""

from bisect import bisect_right
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from enum import Enum, auto

import polars as pl

from rl_analysis.constants import Phase
from rl_analysis.frames import PerPlayer
from rl_analysis.match import Match
from rl_analysis.thresholds import POSSESSION_WINDOW

type PerTeam = dict[int, float | None]
TEAMS = (0, 1)


@dataclass(frozen=True)
class Segment:
    """A stretch of live play: a team's possession, or a loose ball (`team` None). `player` is the
    holder's last toucher at its end, as subtr-actor credits it."""

    start_s: float
    end_s: float
    team: int | None
    player: int | None

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s


@dataclass(frozen=True)
class Turnover:
    """A possession lost on an opponent's touch: `lost_by` held it last, `won_by` took it."""

    time_s: float
    team: int
    lost_by: int | None
    won_by: int | None


@dataclass(frozen=True)
class Possession:
    segments: tuple[Segment, ...]
    turnovers: tuple[Turnover, ...]
    # Each possession split by toucher: who of the team touched it last, from that touch on.
    holders: tuple[Segment, ...]

    @property
    def tracked_s(self) -> float:
        return sum(segment.duration_s for segment in self.segments)


class _State(Enum):
    LOOSE = auto()
    ACQUIRING = auto()
    HELD = auto()
    CHALLENGED = auto()


@dataclass
class _Resolver:
    """subtr-actor's state machine, one frame at a time. `since` is the acquiring team's first
    touch, or the holder's last one."""

    window_s: float
    open_start_s: float
    segments: list[Segment] = field(default_factory=list)
    turnovers: list[Turnover] = field(default_factory=list)
    state: _State = _State.LOOSE
    team: int = 0
    player: int | None = None
    since_s: float = 0.0
    challenger_since_s: float = 0.0
    challenger: int | None = None

    def _close(self, end_s: float, team: int | None, player: int | None) -> None:
        """Ends the open segment at `end_s` with this label, and opens the next one there."""
        if end_s > self.open_start_s:
            self.segments.append(Segment(self.open_start_s, end_s, team, player))
        self.open_start_s = end_s

    def _expired(self, now_s: float, since_s: float) -> bool:
        return now_s - since_s > self.window_s

    def step(self, now_s: float, touched: dict[int, int]) -> None:
        """One live frame. `touched`: the teams that touched the ball on it, with their latest
        toucher."""
        if not touched:
            self._idle(now_s)
        elif len(touched) == 1:
            ((team, player),) = touched.items()
            self._single(now_s, team, player)
        else:
            self._contested(now_s, touched)

    def _idle(self, now_s: float) -> None:
        if self.state is _State.ACQUIRING and self._expired(now_s, self.since_s):
            # A lone touch was a deflection: the ball stays loose.
            self.state = _State.LOOSE
        elif self.state is _State.HELD and self._expired(now_s, self.since_s):
            self._close(self.since_s, self.team, self.player)
            self.state = _State.LOOSE
        elif self.state is _State.CHALLENGED and self._expired(now_s, self.challenger_since_s):
            # Neither side followed up: the holder lost it at its last touch.
            self._close(self.since_s, self.team, self.player)
            self.state = _State.LOOSE

    def _single(self, now_s: float, team: int, player: int) -> None:
        if self.state is _State.LOOSE:
            self.state, self.team, self.player, self.since_s = _State.ACQUIRING, team, player, now_s
        elif self.state is _State.ACQUIRING:
            if team == self.team:
                # Confirmed: credited from the first touch.
                self._close(self.since_s, None, None)
                self.state, self.player, self.since_s = _State.HELD, player, now_s
            else:
                self.team, self.player, self.since_s = team, player, now_s
        elif self.state is _State.HELD:
            if team == self.team:
                self.player, self.since_s = player, now_s
            else:
                self.state, self.challenger_since_s, self.challenger = (
                    _State.CHALLENGED,
                    now_s,
                    player,
                )
        elif team == self.team:
            # The holder repelled the challenge.
            self.state, self.player, self.since_s = _State.HELD, player, now_s
        else:
            self._turnover(now_s, player)

    def _contested(self, now_s: float, touched: dict[int, int]) -> None:
        if self.state is _State.HELD:
            # A fresh challenge, the holder's last touch moved to this frame.
            self.state, self.player, self.since_s = _State.CHALLENGED, touched[self.team], now_s
            self.challenger_since_s, self.challenger = now_s, touched[1 - self.team]
        elif self.state is _State.CHALLENGED:
            self._turnover(now_s, touched[1 - self.team])
        # Loose or acquiring: nobody is clear of it, nothing changes.

    def _turnover(self, now_s: float, player: int) -> None:
        winner = 1 - self.team
        self._close(self.since_s, self.team, self.player)
        self._close(self.challenger_since_s, None, None)
        self.turnovers.append(
            Turnover(self.challenger_since_s, winner, lost_by=self.player, won_by=self.challenger)
        )
        self.state, self.team, self.player, self.since_s = _State.HELD, winner, player, now_s

    def flush(self, end_s: float) -> None:
        """Live play stops: an open possession ends at its last touch, the rest is loose."""
        if self.state in (_State.HELD, _State.CHALLENGED):
            self._close(self.since_s, self.team, self.player)
        self._close(end_s, None, None)
        self.state = _State.LOOSE


def _timeline(match: Match) -> pl.DataFrame:
    """One row per frame of the replay: its frame number, time and phase."""
    return (
        match.frames.group_by("frame")
        .agg(pl.col("time_s").first(), pl.col("phase").first())
        .sort("frame")
    )


def resolve(match: Match) -> Possession | None:
    """The match's possession, or None without detected touches."""
    touches = match.events["touches"]
    if touches is None:
        return None
    timeline = _timeline(match)
    frames: list[int] = timeline["frame"].to_list()
    times: list[float] = timeline["time_s"].to_list()
    phases: list[int] = timeline["phase"].to_list()
    # Touches by frame of the timeline (the latest one at or before theirs), in time order: the
    # latest toucher of a team wins its frame.
    touched: dict[int, dict[int, int]] = {}
    team_touches: list[tuple[float, int, int]] = []
    for touch in sorted(touches, key=lambda touch: (touch["frame"], touch["time_s"])):
        row = bisect_right(frames, touch["frame"]) - 1
        if row < 0:
            continue
        touched.setdefault(row, {})[touch["team"]] = touch["player_idx"]
        team_touches.append((times[row], touch["team"], touch["player_idx"]))

    resolver: _Resolver | None = None
    segments: list[Segment] = []
    turnovers: list[Turnover] = []
    for row, (now_s, phase) in enumerate(zip(times, phases, strict=True)):
        live = phase == Phase.ACTIVE
        if not live:
            if resolver is not None:
                resolver.flush(now_s)
                segments += resolver.segments
                turnovers += resolver.turnovers
                resolver = None
            continue
        if resolver is None:
            resolver = _Resolver(POSSESSION_WINDOW.value, open_start_s=now_s)
        resolver.step(now_s, touched.get(row, {}))
    if resolver is not None:
        resolver.flush(times[-1])
        segments += resolver.segments
        turnovers += resolver.turnovers
    return Possession(tuple(segments), tuple(turnovers), _holders(segments, team_touches))


def _holders(
    segments: list[Segment], team_touches: list[tuple[float, int, int]]
) -> tuple[Segment, ...]:
    """Each team possession split between its touchers: from a touch to the team's next one."""
    holders: list[Segment] = []
    for segment in segments:
        if segment.team is None:
            continue
        own = [
            (time_s, player)
            for time_s, team, player in team_touches
            if team == segment.team and segment.start_s <= time_s <= segment.end_s
        ]
        if not own:
            holders.append(segment)
            continue
        starts = [segment.start_s, *(time_s for time_s, _ in own[1:])]
        ends = [*starts[1:], segment.end_s]
        holders += [
            Segment(start_s, end_s, segment.team, player)
            for start_s, end_s, (_, player) in zip(starts, ends, own, strict=True)
            if end_s > start_s
        ]
    return tuple(holders)


def team_share(match: Match) -> PerTeam:
    """`poss.team_pct`: share of live play the team has the ball, as resolved above; the rest is a
    loose ball, so both teams make less than 100 together. In %. None without detected touches, or
    without live play."""
    possession = resolve(match)
    if possession is None or possession.tracked_s <= 0:
        return dict.fromkeys(TEAMS)
    held: defaultdict[int, float] = defaultdict(float)
    for segment in possession.segments:
        if segment.team is not None:
            held[segment.team] += segment.duration_s
    return {team: 100.0 * held[team] / possession.tracked_s for team in TEAMS}


def player_share(match: Match) -> PerPlayer:
    """`poss.player_pct`: share of live play the player holds the ball for the team: the team's
    possession, from each of the player's touches to the team's next touch. A team's players add up
    to its `poss.team_pct`. In %."""
    possession = resolve(match)
    if possession is None or possession.tracked_s <= 0:
        return dict.fromkeys(match.players)
    held: defaultdict[int, float] = defaultdict(float)
    for holder in possession.holders:
        if holder.player is not None:
            held[holder.player] += holder.duration_s
    return {player: 100.0 * held[player] / possession.tracked_s for player in match.players}


def turnovers_lost(match: Match) -> PerPlayer:
    """`poss.turnovers_lost`: possessions the player's team lost on an opponent's touch, the player
    being the last of the team to touch the ball. A count."""
    possession = resolve(match)
    if possession is None:
        return dict.fromkeys(match.players)
    lost = Counter(turnover.lost_by for turnover in possession.turnovers)
    return {player: float(lost[player]) for player in match.players}


def turnovers_won(match: Match) -> PerPlayer:
    """`poss.turnovers_won`: possessions the player's team won from the opponent, the player's
    touch being the one that took the ball. A count."""
    possession = resolve(match)
    if possession is None:
        return dict.fromkeys(match.players)
    won = Counter(turnover.won_by for turnover in possession.turnovers)
    return {player: float(won[player]) for player in match.players}
