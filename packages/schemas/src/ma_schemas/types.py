"""Typed views of the parser's documents, for the worker. Written by hand and kept in step with the
schemas by a test: a generator would be one more dependency for a few dictionaries."""

from typing import Literal, TypedDict

type Platform = Literal["steam", "epic", "psn", "xbox", "switch", "bot", "unknown"]
type Team = Literal[0, 1]


class ReplayVersion(TypedDict):
    major: int
    minor: int
    net: int | None


class Score(TypedDict):
    blue: int
    orange: int


class HeaderGoal(TypedDict):
    frame: int
    time_s: float | None
    player_name: str | None
    team: Team | None


class HeaderPlayer(TypedDict):
    platform: Platform
    platform_id: str | None
    name: str
    team: Team | None
    score: int
    goals: int
    assists: int
    saves: int
    shots: int
    is_bot: bool


class HeaderDocument(TypedDict):
    schema_version: Literal[1]
    parser_version: str
    game_build: str | None
    build_id: int | None
    changelist: int | None
    replay_version: ReplayVersion
    game_class: str
    match_guid: str | None
    replay_id: str | None
    map: str | None
    played_at: str | None
    played_at_source: Literal["epoch", "date_without_timezone"] | None
    duration_s: float | None
    match_type: str | None
    playlist: str | None
    team_size: int | None
    score: Score
    goals: list[HeaderGoal]
    players: list[HeaderPlayer]


class RosterPlayer(TypedDict):
    player_idx: int
    platform: Platform
    platform_id: str | None
    name: str
    team: Team
    anonymized: bool


class Goal(TypedDict):
    frame: int
    time_s: float
    team: Team
    player_idx: int | None
    score_blue: int | None
    score_orange: int | None


class Demolition(TypedDict):
    frame: int
    time_s: float
    attacker_idx: int | None
    victim_idx: int | None
    x: float
    y: float
    z: float


class PadPickup(TypedDict):
    frame: int
    time_s: float
    phase: Literal[0, 1, 2, 3, 4]
    player_idx: int
    pad_index: int
    size: Literal["big", "small"]
    x: float
    y: float
    z: float


class StatEvent(TypedDict):
    frame: int
    time_s: float
    player_idx: int
    kind: Literal["shot", "save", "assist"]


class Touch(TypedDict):
    frame: int
    time_s: float
    player_idx: int
    team: Team
    ball_speed_change: float
    kind: str | None
    height_band: str | None
    surface: str | None
    contested: bool


class KickoffTaker(TypedDict):
    player_idx: int
    team: Team
    time_to_ball_s: float | None
    start_boost: float | None
    boost_used: float


class Kickoff(TypedDict):
    start_frame: int
    start_time_s: float
    end_frame: int
    end_time_s: float
    kickoff_type: Literal["center", "center_offset", "diagonal", "unknown"]
    first_touch_frame: int | None
    first_touch_time_s: float | None
    first_touch_player_idx: int | None
    winner_team: Team | None
    outcome: Literal["win", "neutral", "unknown"]
    goal: bool
    time_to_goal_s: float | None
    takers: list[KickoffTaker]


class FiftyFifty(TypedDict):
    start_frame: int
    start_time_s: float
    resolve_frame: int
    resolve_time_s: float
    is_kickoff: bool
    blue_player_idx: int | None
    orange_player_idx: int | None
    winner_team: Team | None
    possession_team: Team | None


class BeatenToBall(TypedDict):
    frame: int
    time_s: float
    player_idx: int
    winner_idx: int | None
    team: Team
    distance_at_touch: float
    margin_s: float
    approach_speed: float


class EventsDocument(TypedDict):
    schema_version: Literal[2]
    parser_version: str
    fps: float | None
    playlist_id: int | None
    duration_s: float
    arena_out_of_bounds: bool
    roster: list[RosterPlayer]
    goals: list[Goal]
    demolitions: list[Demolition]
    pad_pickups: list[PadPickup]
    unresolved_pad_pickups: int
    stat_events: list[StatEvent]
    # subtr-actor's detections (docs/PLAN-V2.md, T11.1): None when they failed, or when the
    # document came from a parser older than 0.2.0.
    touches: list[Touch] | None
    kickoffs: list[Kickoff] | None
    fifty_fifties: list[FiftyFifty] | None
    beaten_to_ball: list[BeatenToBall] | None
