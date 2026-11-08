"""What each route answers, declared once. FastAPI checks every response against these and leaves
out any field they do not name: a column added to a query cannot reach a client by mistake, and a
platform id has nowhere to go (section 11 of CLAUDE.md). The site's client is generated from them.

Times stay ISO 8601 strings, as the routes write them.
"""

from typing import Literal

from pydantic import BaseModel

type IdentitySource = Literal["none", "linked_account", "claimed", "memorized"]
type MatchStatus = Literal[
    "pending", "parsing", "header_only", "parsed", "analyzing", "ready", "failed"
]
type UploadStatus = Literal[
    "awaiting_file", "uploaded", "processing", "done", "duplicate", "rejected", "failed"
]


class User(BaseModel):
    id: str
    display_name: str
    locale: Literal["fr", "en"]


class LinkedAccount(BaseModel):
    provider: Literal["steam", "epic"]
    display_name: str | None


class Features(BaseModel):
    epic_login: bool


class Me(BaseModel):
    kind: Literal["none", "anonymous", "user"]
    user: User | None
    linked_accounts: list[LinkedAccount]
    features: Features


class UploadToSend(BaseModel):
    upload_id: str
    status: Literal["awaiting_file"]
    url: str
    method: Literal["PUT"]
    headers: dict[str, str]
    expires_at: str


class UploadDuplicate(BaseModel):
    upload_id: str
    status: Literal["duplicate"]
    match_id: str


class UploadsCreated(BaseModel):
    uploads: list[UploadToSend | UploadDuplicate]


class UploadCompleted(BaseModel):
    upload_id: str
    status: Literal["uploaded"]


class Upload(BaseModel):
    upload_id: str
    name: str
    status: UploadStatus
    rejection: Literal["not_a_replay", "corrupt", "too_large", "size_mismatch"] | None
    match_id: str | None


class UploadPage(BaseModel):
    items: list[Upload]
    next_cursor: str | None


class Score(BaseModel):
    blue: int | None
    orange: int | None


class MatchItem(BaseModel):
    match_id: str
    played_at: str | None
    map: str | None
    playlist: str | None
    team_size: int | None
    score: Score
    status: MatchStatus
    verified: bool
    my_team: int | None
    won: bool | None


class MatchPage(BaseModel):
    items: list[MatchItem]
    next_cursor: str | None


class MatchInfo(BaseModel):
    match_id: str
    played_at: str | None
    map: str | None
    match_type: str | None
    playlist: str | None
    team_size: int | None
    duration_s: float | None
    score: Score
    status: MatchStatus
    arena_out_of_bounds: bool


class Player(BaseModel):
    """A player of the match, by name only: never a platform id."""

    match_player_id: int
    name: str
    team: int
    score: int | None
    goals: int | None
    assists: int | None
    saves: int | None
    shots: int | None
    is_bot: bool
    is_me: bool


class Goal(BaseModel):
    time_s: float
    team: int | None
    player_name: str | None


class MyIdentity(BaseModel):
    match_player_id: int | None
    verified: bool
    identity_source: IdentitySource


class MatchSheet(BaseModel):
    match: MatchInfo
    players: list[Player]
    goals: list[Goal]
    metrics: dict[str, dict[str, float | None]]
    me: MyIdentity
    needs_identity: bool


class IdentityChosen(BaseModel):
    verified: bool
    identity_source: IdentitySource


class Stats(BaseModel):
    matches_count: int
    verified_count: int
    averages: dict[str, float | None]


class HistoryPoint(BaseModel):
    match_id: str
    played_at: str | None
    value: float | None
    verified: bool


class History(BaseModel):
    metric_id: str
    points: list[HistoryPoint]


class Health(BaseModel):
    status: Literal["ok"]


class ErrorDetail(BaseModel):
    code: str
    message_key: str
    details: dict[str, object]


class Error(BaseModel):
    """Every error of the API, whatever the route."""

    error: ErrorDetail
