"""Matches and identity, against PostgreSQL with the API's own role."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ma_api.settings import PREFIX, Settings
from ma_db.testing import Connection, Factory, count

from .helpers import (
    ME,
    STEAM_IDS,
    FakeProviders,
    FakeStore,
    anonymous_session,
    browser_for,
    steam_sign_in,
    user_session,
)

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_limits")]

MATCHES = f"{PREFIX}/matches"


def signed_in(browser: TestClient, conn: Connection, make: Factory) -> uuid.UUID:
    user = make.user()
    browser.cookies.set("session", user_session(conn, user))
    return user


def set_match(conn: Connection, match: uuid.UUID, **fields: Any) -> None:
    for column, value in fields.items():
        # Column names come from this test file.
        conn.execute(f"UPDATE matches SET {column} = %s WHERE id = %s".encode(), (value, match))


def goal(conn: Connection, match: uuid.UUID, time_s: float, team: int, actor: int | None) -> None:
    conn.execute(
        "INSERT INTO match_events (match_id, kind, frame, time_s, team, actor_player_id) "
        "VALUES (%s, 'goal', 1, %s, %s, %s)",
        (match, time_s, team, actor),
    )


def claims_of(conn: Connection, user: uuid.UUID) -> int:
    return count(conn, "SELECT count(*) FROM player_claims WHERE user_id = %s", user)


def link_state(conn: Connection, link: int) -> tuple[int | None, str, bool]:
    row = conn.execute(
        "SELECT match_player_id, identity_source, verified FROM user_matches WHERE id = %s", (link,)
    ).fetchone()
    assert row is not None
    return row[0], row[1], row[2]


def test_nobody_has_no_matches(browser: TestClient) -> None:
    match = uuid.uuid4()
    for response in (
        browser.get(MATCHES),
        browser.get(f"{MATCHES}/{match}"),
        browser.post(f"{MATCHES}/{match}/identity", json={"match_player_id": 1}),
    ):
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "not_signed_in"


def test_the_list_describes_each_match(
    browser: TestClient, conn: Connection, make: Factory
) -> None:
    user = signed_in(browser, conn, make)
    match = make.match()
    played_at = datetime(2026, 11, 1, 20, 0, tzinfo=UTC)
    set_match(
        conn,
        match,
        played_at=played_at,
        map="a_map",
        playlist="ranked_doubles",
        team_size=2,
        score_blue=3,
        score_orange=1,
    )
    player = make.player(match, team=0)
    make.user_match(match, user_id=user, match_player_id=player, identity_source="claimed")
    body = browser.get(MATCHES).json()
    assert body == {
        "items": [
            {
                "match_id": str(match),
                "played_at": played_at.isoformat(),
                "map": "a_map",
                "playlist": "ranked_doubles",
                "team_size": 2,
                "score": {"blue": 3, "orange": 1},
                "status": "ready",
                "verified": False,
                "my_team": 0,
                "won": True,
            }
        ],
        "next_cursor": None,
    }


@pytest.mark.parametrize(
    ("team", "blue", "orange", "won"),
    [
        (0, 3, 1, True),
        (0, 1, 3, False),
        (1, 1, 3, True),
        (1, 3, 1, False),
        (0, 2, 2, False),
        (0, None, 1, None),
    ],
)
def test_won_depends_on_my_team(
    browser: TestClient,
    conn: Connection,
    make: Factory,
    team: int,
    blue: int | None,
    orange: int,
    won: bool | None,
) -> None:
    user = signed_in(browser, conn, make)
    match = make.match()
    set_match(conn, match, score_blue=blue, score_orange=orange)
    player = make.player(match, team=team)
    make.user_match(match, user_id=user, match_player_id=player, identity_source="claimed")
    item = browser.get(MATCHES).json()["items"][0]
    assert item["my_team"] == team
    assert item["won"] is won


def test_without_an_identity_nothing_is_known_about_my_team(
    browser: TestClient, conn: Connection, make: Factory
) -> None:
    user = signed_in(browser, conn, make)
    match = make.match()
    set_match(conn, match, score_blue=1, score_orange=0)
    make.user_match(match, user_id=user)
    item = browser.get(MATCHES).json()["items"][0]
    assert item["my_team"] is None
    assert item["won"] is None


def test_the_scope_filters_verified_matches(
    browser: TestClient, conn: Connection, make: Factory
) -> None:
    user = signed_in(browser, conn, make)
    verified, unverified = make.match(), make.match()
    player = make.player(verified)
    make.user_match(
        verified,
        user_id=user,
        match_player_id=player,
        identity_source="linked_account",
        verified=True,
    )
    make.user_match(unverified, user_id=user)
    every = {item["match_id"] for item in browser.get(MATCHES).json()["items"]}
    assert every == {str(verified), str(unverified)}
    only = browser.get(MATCHES, params={"scope": "verified"}).json()["items"]
    assert [item["match_id"] for item in only] == [str(verified)]
    assert browser.get(MATCHES, params={"scope": "nonsense"}).status_code == 400


def test_the_list_goes_page_by_page_from_the_latest(
    browser: TestClient, conn: Connection, make: Factory
) -> None:
    user = signed_in(browser, conn, make)
    start = datetime(2026, 11, 1, tzinfo=UTC)
    expected = []
    for days in range(5):
        match = make.match()
        # Two share a date, and one has none: it goes by its arrival, which is now.
        played_at = None if days == 4 else start + timedelta(days=min(days, 2))
        set_match(conn, match, played_at=played_at)
        make.user_match(match, user_id=user)
        expected.append(match)
    seen: list[str] = []
    params: dict[str, Any] = {"limit": 2}
    pages = 0
    while True:
        body = browser.get(MATCHES, params=params).json()
        seen += [item["match_id"] for item in body["items"]]
        pages += 1
        if body["next_cursor"] is None:
            break
        params["cursor"] = body["next_cursor"]
    assert pages == 3
    assert sorted(seen) == sorted(str(match) for match in expected)
    assert seen[0] == str(expected[4])
    assert seen[-1] == str(expected[0])


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 201}, {"cursor": "nonsense"}])
def test_bad_list_parameters_are_invalid(
    browser: TestClient, conn: Connection, make: Factory, params: dict[str, Any]
) -> None:
    signed_in(browser, conn, make)
    assert browser.get(MATCHES, params=params).status_code == 400


def test_the_list_shows_my_matches_only(
    browser: TestClient, conn: Connection, make: Factory
) -> None:
    mine = signed_in(browser, conn, make)
    other = make.match()
    make.user_match(other, user_id=make.user())
    assert browser.get(MATCHES).json()["items"] == []
    match = make.match()
    make.user_match(match, user_id=mine)
    assert [item["match_id"] for item in browser.get(MATCHES).json()["items"]] == [str(match)]


def test_an_anonymous_session_has_its_matches(
    browser: TestClient, conn: Connection, make: Factory
) -> None:
    session, token = anonymous_session(conn)
    match = make.match()
    make.user_match(match, anonymous_session_id=session)
    browser.cookies.set("anon", token)
    assert [item["match_id"] for item in browser.get(MATCHES).json()["items"]] == [str(match)]
    assert browser.get(f"{MATCHES}/{match}").status_code == 200


def test_someone_elses_match_does_not_exist_for_me(
    browser: TestClient, conn: Connection, make: Factory
) -> None:
    signed_in(browser, conn, make)
    match = make.match()
    player = make.player(match)
    make.user_match(match, user_id=make.user())
    for response in (
        browser.get(f"{MATCHES}/{match}"),
        browser.post(f"{MATCHES}/{match}/identity", json={"match_player_id": player}),
        browser.get(f"{MATCHES}/{uuid.uuid4()}"),
    ):
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"


def test_the_situations_of_a_match_show_only_the_facts_of_their_kind(
    browser: TestClient, conn: Connection, make: Factory
) -> None:
    """Annex G of docs/PLAN-V2.md: in time order, players as match_player_id, and `details` cut to
    what each kind has: whatever else the row holds, a platform id above all, never comes out."""
    user = signed_in(browser, conn, make)
    match = make.match()
    me = make.player(match, team=0, name="Me")
    them = make.player(match, team=1, name="Them")
    make.user_match(match, user_id=user, match_player_id=me, identity_source="claimed")
    defenders = [
        {
            "player": me,
            "goal_distance": 2500.0,
            "boost": 12.0,
            "demolished": False,
            "last_back": True,
        }
    ]
    goal_context = make.situation(
        match,
        "goal_context",
        40.0,
        game_time_s=35.5,
        team=0,
        player_ids=[me],
        tags=["last_back_far", "last_back_low_boost"],
        details={
            "window_s": 10.0,
            "shot_clock_s": 34.8,
            "last_touch": {"player": them, "team": 1},
            "lost_ball": None,
            "defenders": defenders,
            "platform_id": "76561190000000000",
        },
    )
    turnover = make.situation(
        match, "turnover", 12.0, team=1, player_ids=[them, me], details={"platform_id": "x"}
    )

    body = browser.get(f"{MATCHES}/{match}").json()
    assert body["situations"] == [
        {
            "id": turnover,
            "kind": "turnover",
            "time_s": 12.0,
            "game_time_s": None,
            "team": 1,
            "players": [them, me],
            "tags": [],
            "details": {},
        },
        {
            "id": goal_context,
            "kind": "goal_context",
            "time_s": 40.0,
            "game_time_s": 35.5,
            "team": 0,
            "players": [me],
            "tags": ["last_back_far", "last_back_low_boost"],
            "details": {
                "window_s": 10.0,
                "shot_clock_s": 34.8,
                "last_touch": {"player": them, "team": 1},
                "lost_ball": None,
                "defenders": defenders,
            },
        },
    ]
    assert "76561190000000000" not in browser.get(f"{MATCHES}/{match}").text


def test_a_match_without_analysis_has_no_situation(
    browser: TestClient, conn: Connection, make: Factory
) -> None:
    user = signed_in(browser, conn, make)
    match = make.match()
    me = make.player(match, team=0, name="Me")
    make.user_match(match, user_id=user, match_player_id=me, identity_source="claimed")
    assert browser.get(f"{MATCHES}/{match}").json()["situations"] == []


def test_a_bad_match_id_is_invalid(browser: TestClient, conn: Connection, make: Factory) -> None:
    signed_in(browser, conn, make)
    assert browser.get(f"{MATCHES}/not-an-id").status_code == 400


def test_the_match_sheet(browser: TestClient, conn: Connection, make: Factory) -> None:
    user = signed_in(browser, conn, make)
    match = make.match()
    played_at = datetime(2026, 11, 1, 20, 0, tzinfo=UTC)
    set_match(
        conn,
        match,
        played_at=played_at,
        map="a_map",
        match_type="Online",
        playlist="ranked_doubles",
        team_size=1,
        duration_s=300.5,
        score_blue=1,
        score_orange=1,
        arena_out_of_bounds=True,
    )
    me = make.player(match, team=0, name="Me")
    them = make.player(match, team=1, name="Them")
    conn.execute(
        "UPDATE match_players SET score = 100, goals = 1, assists = 0, saves = 2, shots = 3 "
        "WHERE id = %s",
        (me,),
    )
    goal(conn, match, 20.5, 1, them)
    goal(conn, match, 10.5, 0, me)
    goal(conn, match, 30.5, 0, None)
    make.metric(me, "boost.avg", 42.5)
    make.metric(them, "boost.avg", 12.5)
    make.team_metric(match, 0, value=31.5)
    make.team_metric(match, 1, value=22.0)
    make.user_match(match, user_id=user, match_player_id=me, identity_source="claimed")

    body = browser.get(f"{MATCHES}/{match}").json()
    assert body["match"] == {
        "match_id": str(match),
        "played_at": played_at.isoformat(),
        "map": "a_map",
        "match_type": "Online",
        "playlist": "ranked_doubles",
        "team_size": 1,
        "duration_s": 300.5,
        "score": {"blue": 1, "orange": 1},
        "status": "ready",
        "arena_out_of_bounds": True,
        "game_length_s": None,
        "overtime_from_s": None,
    }
    assert body["players"] == [
        {
            "match_player_id": me,
            "name": "Me",
            "team": 0,
            "score": 100,
            "goals": 1,
            "assists": 0,
            "saves": 2,
            "shots": 3,
            "is_bot": False,
            "is_me": True,
        },
        {
            "match_player_id": them,
            "name": "Them",
            "team": 1,
            "score": None,
            "goals": None,
            "assists": None,
            "saves": None,
            "shots": None,
            "is_bot": False,
            "is_me": False,
        },
    ]
    assert body["goals"] == [
        {"time_s": 10.5, "team": 0, "player_name": "Me", "game_time_s": None},
        {"time_s": 20.5, "team": 1, "player_name": "Them", "game_time_s": None},
        {"time_s": 30.5, "team": 0, "player_name": None, "game_time_s": None},
    ]
    assert body["metrics"] == {str(me): {"boost.avg": 42.5}, str(them): {"boost.avg": 12.5}}
    assert body["team_metrics"] == {"0": {"poss.team_pct": 31.5}, "1": {"poss.team_pct": 22.0}}
    assert body["me"] == {
        "match_player_id": me,
        "verified": False,
        "identity_source": "claimed",
    }
    assert body["needs_identity"] is False


def test_a_match_without_an_identity_asks_for_one(
    browser: TestClient, conn: Connection, make: Factory
) -> None:
    user = signed_in(browser, conn, make)
    match = make.match()
    make.player(match)
    make.user_match(match, user_id=user)
    body = browser.get(f"{MATCHES}/{match}").json()
    assert body["needs_identity"] is True
    assert body["me"]["match_player_id"] is None


def test_a_match_not_parsed_yet_asks_for_nothing(
    browser: TestClient, conn: Connection, make: Factory
) -> None:
    user = signed_in(browser, conn, make)
    match = make.match("pending")
    make.user_match(match, user_id=user)
    body = browser.get(f"{MATCHES}/{match}").json()
    assert body["match"]["status"] == "pending"
    assert body["players"] == []
    assert body["needs_identity"] is False


@pytest.fixture
def full_match(conn: Connection, make: Factory) -> dict[str, Any]:
    """A match where every player has an id, all of them known to the test."""
    match = make.match()
    ids = [next(STEAM_IDS), "epicaccount0000000000000000000a1", "psn-id-of-a-third-party"]
    players = [
        make.player(match, platform="steam", platform_id=ids[0], team=0),
        make.player(match, platform="epic", platform_id=ids[1], team=1, name="An anonymous name"),
        make.player(match, platform="psn", platform_id=ids[2], team=1),
    ]
    conn.execute("UPDATE match_players SET anonymized = true WHERE id = %s", (players[1],))
    for player in players:
        make.metric(player)
    goal(conn, match, 1.0, 0, players[0])
    return {"match": match, "ids": ids, "players": players}


def assert_no_platform_id(text: str, ids: list[str]) -> None:
    assert "platform_id" not in text
    assert "provider_account_id" not in text
    for platform_id in ids:
        assert platform_id not in text


def test_no_response_ever_holds_a_platform_id(
    browser: TestClient,
    settings: Settings,
    providers: FakeProviders,
    conn: Connection,
    make: Factory,
    full_match: dict[str, Any],
) -> None:
    """The cross-cutting check of T5.13, through every route a match can reach."""
    my_id = full_match["ids"][0]
    steam_sign_in(browser, my_id)
    user = browser.get(ME).json()["user"]["id"]
    match = full_match["match"]
    upload = make.upload(user_id=uuid.UUID(user), match_id=match)
    make.user_match(match, user_id=uuid.UUID(user))
    responses = [
        browser.get(ME),
        browser.get(MATCHES),
        browser.get(f"{MATCHES}/{match}"),
        browser.post(
            f"{MATCHES}/{match}/identity", json={"match_player_id": full_match["players"][1]}
        ),
        browser.get(f"{PREFIX}/uploads"),
        browser.get(f"{PREFIX}/uploads/{upload}"),
    ]
    for response in responses:
        assert response.headers["content-type"] == "application/json"
        assert_no_platform_id(response.text, full_match["ids"])


def test_the_openapi_description_names_no_platform_id(browser: TestClient) -> None:
    """Every documented response of the API, including the routes to come."""
    assert_no_platform_id(browser.get(f"{PREFIX}/openapi.json").text, [])


def test_an_anonymized_player_shows_their_anonymous_name(
    browser: TestClient, conn: Connection, make: Factory, full_match: dict[str, Any]
) -> None:
    user = signed_in(browser, conn, make)
    make.user_match(full_match["match"], user_id=user)
    body = browser.get(f"{MATCHES}/{full_match['match']}").json()
    assert "An anonymous name" in {player["name"] for player in body["players"]}


def test_choosing_a_player(browser: TestClient, conn: Connection, make: Factory) -> None:
    user = signed_in(browser, conn, make)
    match = make.match()
    player = make.player(match, platform_id="choice-1")
    link = make.user_match(match, user_id=user)
    response = browser.post(f"{MATCHES}/{match}/identity", json={"match_player_id": player})
    assert response.status_code == 200
    assert response.json() == {"verified": False, "identity_source": "claimed"}
    assert link_state(conn, link) == (player, "claimed", False)
    assert claims_of(conn, user) == 1
    assert browser.get(f"{MATCHES}/{match}").json()["needs_identity"] is False


def test_the_choice_reaches_my_other_matches(
    browser: TestClient, conn: Connection, make: Factory
) -> None:
    user = signed_in(browser, conn, make)
    first, later = make.match(), make.match()
    player = make.player(first, platform_id="choice-2")
    same_one = make.player(later, platform_id="choice-2")
    make.player(later, platform_id="someone")
    make.user_match(first, user_id=user)
    next_link = make.user_match(later, user_id=user)
    browser.post(f"{MATCHES}/{first}/identity", json={"match_player_id": player})
    assert link_state(conn, next_link) == (same_one, "memorized", False)


def test_changing_my_mind_forgets_the_wrong_player(
    browser: TestClient, conn: Connection, make: Factory
) -> None:
    user = signed_in(browser, conn, make)
    first, later = make.match(), make.match()
    wrong = make.player(first, platform_id="wrong-one")
    right = make.player(first, platform_id="right-one")
    make.player(later, platform_id="wrong-one")
    right_later = make.player(later, platform_id="right-one")
    make.user_match(first, user_id=user)
    later_link = make.user_match(later, user_id=user)
    browser.post(f"{MATCHES}/{first}/identity", json={"match_player_id": wrong})
    browser.post(f"{MATCHES}/{first}/identity", json={"match_player_id": right})
    assert claims_of(conn, user) == 1
    assert link_state(conn, later_link) == (right_later, "memorized", False)


def test_a_choice_cannot_verify_a_match(
    browser: TestClient, conn: Connection, make: Factory
) -> None:
    """Choosing a player who is not one's linked account proves nothing."""
    user = signed_in(browser, conn, make)
    make.linked_account(user, "steam", next(STEAM_IDS))
    match = make.match()
    player = make.player(match, platform_id=next(STEAM_IDS))
    link = make.user_match(match, user_id=user)
    response = browser.post(f"{MATCHES}/{match}/identity", json={"match_player_id": player})
    assert response.json() == {"verified": False, "identity_source": "claimed"}
    assert link_state(conn, link)[2] is False


def test_choosing_my_own_linked_account_is_a_proof(
    browser: TestClient, conn: Connection, make: Factory
) -> None:
    user = signed_in(browser, conn, make)
    steam_id = next(STEAM_IDS)
    make.linked_account(user, "steam", steam_id)
    match = make.match()
    player = make.player(match, platform_id=steam_id)
    make.user_match(match, user_id=user)
    response = browser.post(f"{MATCHES}/{match}/identity", json={"match_player_id": player})
    assert response.json() == {"verified": True, "identity_source": "linked_account"}


def test_a_verified_match_is_locked(browser: TestClient, conn: Connection, make: Factory) -> None:
    user = signed_in(browser, conn, make)
    match = make.match()
    mine = make.player(match)
    other = make.player(match)
    link = make.user_match(
        match, user_id=user, match_player_id=mine, identity_source="linked_account", verified=True
    )
    response = browser.post(f"{MATCHES}/{match}/identity", json={"match_player_id": other})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "identity_locked"
    assert link_state(conn, link) == (mine, "linked_account", True)


def test_a_player_of_another_match_is_refused(
    browser: TestClient, conn: Connection, make: Factory
) -> None:
    user = signed_in(browser, conn, make)
    match = make.match()
    elsewhere = make.player(make.match())
    link = make.user_match(match, user_id=user)
    response = browser.post(f"{MATCHES}/{match}/identity", json={"match_player_id": elsewhere})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "not_a_player"
    assert link_state(conn, link) == (None, "none", False)


def test_a_bot_cannot_be_chosen(browser: TestClient, conn: Connection, make: Factory) -> None:
    user = signed_in(browser, conn, make)
    match = make.match()
    bot = make.player(match, platform="bot")
    conn.execute("UPDATE match_players SET is_bot = true WHERE id = %s", (bot,))
    make.user_match(match, user_id=user)
    response = browser.post(f"{MATCHES}/{match}/identity", json={"match_player_id": bot})
    assert response.status_code == 422
    assert browser.get(f"{MATCHES}/{match}").json()["needs_identity"] is False


def test_a_player_without_an_id_is_chosen_but_not_memorized(
    browser: TestClient, conn: Connection, make: Factory
) -> None:
    user = signed_in(browser, conn, make)
    match = make.match()
    row = conn.execute(
        "INSERT INTO match_players (match_id, platform, platform_id, display_name, team) "
        "VALUES (%s, 'epic', NULL, 'Old replay', 0) RETURNING id",
        (match,),
    ).fetchone()
    assert row is not None
    make.user_match(match, user_id=user)
    response = browser.post(f"{MATCHES}/{match}/identity", json={"match_player_id": row[0]})
    assert response.status_code == 200
    assert claims_of(conn, user) == 0


@pytest.mark.parametrize("body", [{}, {"match_player_id": "me"}, {"other": 1}])
def test_a_bad_identity_body_is_invalid(
    browser: TestClient, conn: Connection, make: Factory, body: dict[str, Any]
) -> None:
    user = signed_in(browser, conn, make)
    match = make.match()
    make.user_match(match, user_id=user)
    assert browser.post(f"{MATCHES}/{match}/identity", json=body).status_code == 400


def test_another_site_cannot_choose(browser: TestClient, conn: Connection, make: Factory) -> None:
    user = signed_in(browser, conn, make)
    match = make.match()
    player = make.player(match)
    make.user_match(match, user_id=user)
    response = browser.post(
        f"{MATCHES}/{match}/identity",
        json={"match_player_id": player},
        headers={"Origin": "https://evil.test"},
    )
    assert response.status_code == 403


def test_an_anonymous_choice_comes_along_at_sign_in(
    settings: Settings, providers: FakeProviders, conn: Connection, make: Factory
) -> None:
    """Chosen anonymously, then signed in: a later match knows the player, unverified."""
    session, token = anonymous_session(conn)
    steam_id = next(STEAM_IDS)
    first, later = make.match(), make.match()
    player = make.player(first, platform_id="anon-choice")
    same_one = make.player(later, platform_id="anon-choice")
    make.user_match(first, anonymous_session_id=session)
    with browser_for(settings, providers, FakeStore()) as client:
        client.cookies.set("anon", token)
        client.post(f"{MATCHES}/{first}/identity", json={"match_player_id": player})
        steam_sign_in(client, steam_id)
        user = uuid.UUID(client.get(ME).json()["user"]["id"])
    link = make.user_match(later, user_id=user)
    with browser_for(settings, providers, FakeStore()) as client:
        steam_sign_in(client, steam_id)
    assert link_state(conn, link) == (same_one, "memorized", False)


def test_the_sheet_gives_the_game_clock(
    browser: TestClient, conn: Connection, make: Factory
) -> None:
    """Written by the analysis (A63): the timeline of goals runs on it."""
    user = signed_in(browser, conn, make)
    match = make.match("ready")
    scorer = make.player(match, team=0, name="Me")
    goal(conn, match, 400.0, 0, scorer)
    conn.execute(
        "UPDATE matches SET game_length_s = 342.0, overtime_from_s = 302.0 WHERE id = %s", (match,)
    )
    conn.execute("UPDATE match_events SET game_time_s = 342.0 WHERE match_id = %s", (match,))
    make.user_match(match, user_id=user, match_player_id=scorer, identity_source="claimed")
    body = browser.get(f"{MATCHES}/{match}").json()
    assert body["match"]["game_length_s"] == 342.0
    assert body["match"]["overtime_from_s"] == 302.0
    assert body["goals"][0]["game_time_s"] == 342.0
    assert body["goals"][0]["time_s"] == 400.0


def view_of(client: TestClient, match: uuid.UUID) -> Any:
    return client.get(f"{MATCHES}/{match}/view")


def test_the_owner_gets_a_short_url_to_the_view(
    settings: Settings, providers: FakeProviders, conn: Connection, make: Factory
) -> None:
    match = make.match()
    set_match(conn, match, view_key=f"views/{match}.json.gz")
    with browser_for(settings, providers, FakeStore()) as client:
        user = signed_in(client, conn, make)
        make.user_match(match, user_id=user)
        before = datetime.now(UTC)
        body = view_of(client, match).json()
    assert body["url"] == f"https://store.test/views/{match}.json.gz?ttl={settings.view_url_ttl_s}"
    expires_at = datetime.fromisoformat(body["expires_at"])
    assert timedelta(seconds=590) < expires_at - before <= timedelta(seconds=610)


def test_no_view_yet_is_not_available(
    settings: Settings, providers: FakeProviders, conn: Connection, make: Factory
) -> None:
    """Before the analysis, for a match read from its header, or while a new parse waits."""
    match = make.match("header_only")
    with browser_for(settings, providers, FakeStore()) as client:
        make.user_match(match, user_id=signed_in(client, conn, make))
        response = view_of(client, match)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_available"


def test_someone_elses_view_does_not_exist_for_me(
    settings: Settings, providers: FakeProviders, conn: Connection, make: Factory
) -> None:
    match = make.match()
    set_match(conn, match, view_key=f"views/{match}.json.gz")
    make.user_match(match, user_id=make.user())
    with browser_for(settings, providers, FakeStore()) as client:
        signed_in(client, conn, make)
        response = view_of(client, match)
        nobody = client.get(f"{MATCHES}/{match}/view", cookies={"session": ""})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert nobody.status_code in (401, 404)
