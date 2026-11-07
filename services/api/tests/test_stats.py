"""`/stats/me` against sums worked out by hand, on synthetic matches."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ma_api.settings import PREFIX
from ma_db.testing import Connection, Factory

from .helpers import anonymous_session, user_session

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_limits")]

STATS = f"{PREFIX}/stats/me"
HISTORY = f"{STATS}/history"
START = datetime(2026, 11, 1, tzinfo=UTC)
METRIC = "boost.avg"


def signed_in(browser: TestClient, conn: Connection, make: Factory) -> uuid.UUID:
    user = make.user()
    browser.cookies.set("session", user_session(conn, user))
    return user


def played(
    conn: Connection,
    make: Factory,
    user: uuid.UUID,
    days: int,
    value: float | None,
    *,
    verified: bool = False,
    metric_id: str = METRIC,
) -> uuid.UUID:
    """A match the user played, `days` after the start, with this value for them."""
    match = make.match()
    conn.execute(
        "UPDATE matches SET played_at = %s WHERE id = %s", (START + timedelta(days=days), match)
    )
    player = make.player(match)
    make.metric(player, metric_id, value)
    make.user_match(
        match,
        user_id=user,
        match_player_id=player,
        identity_source="linked_account" if verified else "claimed",
        verified=verified,
    )
    return match


def test_nobody_has_no_stats(browser: TestClient) -> None:
    for response in (browser.get(STATS), browser.get(HISTORY, params={"metric_id": METRIC})):
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "not_signed_in"


def test_no_match_yet(browser: TestClient, conn: Connection, make: Factory) -> None:
    signed_in(browser, conn, make)
    assert browser.get(STATS).json() == {"matches_count": 0, "verified_count": 0, "averages": {}}
    assert browser.get(HISTORY, params={"metric_id": METRIC}).json() == {
        "metric_id": METRIC,
        "points": [],
    }


def test_the_average_gives_each_match_the_same_weight(
    browser: TestClient, conn: Connection, make: Factory
) -> None:
    user = signed_in(browser, conn, make)
    for days, value in enumerate([10.0, 20.0, 60.0]):
        played(conn, make, user, days, value, verified=days == 0)
    assert browser.get(STATS).json() == {
        "matches_count": 3,
        "verified_count": 1,
        "averages": {METRIC: 30.0},
    }


def test_each_metric_has_its_own_average(
    browser: TestClient, conn: Connection, make: Factory
) -> None:
    user = signed_in(browser, conn, make)
    played(conn, make, user, 0, 10.0)
    played(conn, make, user, 1, 4.0, metric_id="move.speed_avg")
    assert browser.get(STATS).json()["averages"] == {METRIC: 10.0, "move.speed_avg": 4.0}


def test_last_keeps_the_latest_matches(
    browser: TestClient, conn: Connection, make: Factory
) -> None:
    user = signed_in(browser, conn, make)
    # Out of order on purpose: what counts is when they were played.
    for days, value in [(2, 30.0), (0, 10.0), (3, 50.0), (1, 20.0)]:
        played(conn, make, user, days, value)
    body = browser.get(STATS, params={"last": 2}).json()
    assert body["matches_count"] == 2
    assert body["averages"] == {METRIC: 40.0}


def test_the_scope_keeps_verified_matches(
    browser: TestClient, conn: Connection, make: Factory
) -> None:
    user = signed_in(browser, conn, make)
    played(conn, make, user, 0, 10.0, verified=True)
    played(conn, make, user, 1, 90.0)
    body = browser.get(STATS, params={"scope": "verified"}).json()
    assert body == {"matches_count": 1, "verified_count": 1, "averages": {METRIC: 10.0}}


def test_last_applies_after_the_scope(browser: TestClient, conn: Connection, make: Factory) -> None:
    user = signed_in(browser, conn, make)
    played(conn, make, user, 0, 10.0, verified=True)
    played(conn, make, user, 1, 90.0)
    body = browser.get(STATS, params={"scope": "verified", "last": 1}).json()
    assert body["averages"] == {METRIC: 10.0}


def test_an_undefined_value_is_left_out(
    browser: TestClient, conn: Connection, make: Factory
) -> None:
    user = signed_in(browser, conn, make)
    played(conn, make, user, 0, 10.0)
    played(conn, make, user, 1, None)
    assert browser.get(STATS).json()["averages"] == {METRIC: 10.0}


def test_a_metric_undefined_everywhere_is_null(
    browser: TestClient, conn: Connection, make: Factory
) -> None:
    user = signed_in(browser, conn, make)
    played(conn, make, user, 0, None, metric_id="pos.pct_last_back")
    assert browser.get(STATS).json()["averages"] == {"pos.pct_last_back": None}


def test_a_match_without_metrics_takes_no_place(
    browser: TestClient, conn: Connection, make: Factory
) -> None:
    user = signed_in(browser, conn, make)
    played(conn, make, user, 0, 10.0)
    later = make.match("header_only")
    conn.execute(
        "UPDATE matches SET played_at = %s WHERE id = %s", (START + timedelta(days=1), later)
    )
    make.user_match(
        later, user_id=user, match_player_id=make.player(later), identity_source="claimed"
    )
    body = browser.get(STATS, params={"last": 1}).json()
    assert body["matches_count"] == 1
    assert body["averages"] == {METRIC: 10.0}


def test_a_match_without_an_identity_does_not_count(
    browser: TestClient, conn: Connection, make: Factory
) -> None:
    user = signed_in(browser, conn, make)
    match = make.match()
    make.metric(make.player(match), METRIC, 99.0)
    make.user_match(match, user_id=user)
    assert browser.get(STATS).json()["matches_count"] == 0


def test_only_my_own_player_counts(browser: TestClient, conn: Connection, make: Factory) -> None:
    user = signed_in(browser, conn, make)
    match = played(conn, make, user, 0, 10.0)
    make.metric(make.player(match), METRIC, 90.0)
    assert browser.get(STATS).json()["averages"] == {METRIC: 10.0}


def test_someone_elses_matches_do_not_count(
    browser: TestClient, conn: Connection, make: Factory
) -> None:
    signed_in(browser, conn, make)
    played(conn, make, make.user(), 0, 90.0)
    assert browser.get(STATS).json()["matches_count"] == 0


def test_an_anonymous_session_has_its_stats(
    browser: TestClient, conn: Connection, make: Factory
) -> None:
    session, token = anonymous_session(conn)
    match = make.match()
    player = make.player(match)
    make.metric(player, METRIC, 10.0)
    make.user_match(
        match, anonymous_session_id=session, match_player_id=player, identity_source="claimed"
    )
    browser.cookies.set("anon", token)
    assert browser.get(STATS).json()["averages"] == {METRIC: 10.0}


def test_the_history_goes_from_the_oldest(
    browser: TestClient, conn: Connection, make: Factory
) -> None:
    user = signed_in(browser, conn, make)
    later = played(conn, make, user, 1, 20.0)
    first = played(conn, make, user, 0, 10.0, verified=True)
    body = browser.get(HISTORY, params={"metric_id": METRIC}).json()
    assert body == {
        "metric_id": METRIC,
        "points": [
            {
                "match_id": str(first),
                "played_at": START.isoformat(),
                "value": 10.0,
                "verified": True,
            },
            {
                "match_id": str(later),
                "played_at": (START + timedelta(days=1)).isoformat(),
                "value": 20.0,
                "verified": False,
            },
        ],
    }


def test_the_history_keeps_the_latest_and_the_scope(
    browser: TestClient, conn: Connection, make: Factory
) -> None:
    user = signed_in(browser, conn, make)
    for days, value in [(0, 10.0), (1, 20.0), (2, 30.0)]:
        played(conn, make, user, days, value, verified=days != 2)
    points = browser.get(HISTORY, params={"metric_id": METRIC, "last": 2}).json()["points"]
    assert [point["value"] for point in points] == [20.0, 30.0]
    points = browser.get(
        HISTORY, params={"metric_id": METRIC, "last": 2, "scope": "verified"}
    ).json()["points"]
    assert [point["value"] for point in points] == [10.0, 20.0]


def test_the_history_keeps_an_undefined_value(
    browser: TestClient, conn: Connection, make: Factory
) -> None:
    user = signed_in(browser, conn, make)
    played(conn, make, user, 0, None)
    points = browser.get(HISTORY, params={"metric_id": METRIC}).json()["points"]
    assert [point["value"] for point in points] == [None]


def test_an_unknown_metric_is_refused(browser: TestClient, conn: Connection, make: Factory) -> None:
    signed_in(browser, conn, make)
    response = browser.get(HISTORY, params={"metric_id": "boost.nonsense"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unknown_metric"


@pytest.mark.parametrize(
    ("route", "params"),
    [
        (STATS, {"last": 0}),
        (STATS, {"last": 201}),
        (STATS, {"last": "many"}),
        (STATS, {"scope": "nonsense"}),
        (HISTORY, {}),
        (HISTORY, {"metric_id": METRIC, "last": 0}),
        (HISTORY, {"metric_id": METRIC, "scope": "nonsense"}),
    ],
)
def test_bad_parameters_are_invalid(
    browser: TestClient, conn: Connection, make: Factory, route: str, params: dict[str, Any]
) -> None:
    signed_in(browser, conn, make)
    response = browser.get(route, params=params)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"
