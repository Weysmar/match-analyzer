"""Behavior shared by every route. Most of this needs no database."""

import logging
from collections.abc import Iterator
from typing import Any

import httpx2
import pytest
from fastapi import Body, FastAPI
from fastapi.testclient import TestClient

from ma_api.app import create_app
from ma_api.errors import ApiError
from ma_api.settings import PREFIX, Settings

SITE = "http://testserver"
UNREACHABLE = "postgresql://nobody@127.0.0.1:1/nothing"


def app_without_database(**overrides: object) -> FastAPI:
    settings = Settings(
        database_url=UNREACHABLE,
        site_url=str(overrides.get("site_url", SITE)),
        production=bool(overrides.get("production", False)),
        database_timeout_s=0.2,
    )
    app = create_app(settings)

    @app.post("/test/echo")
    def echo(number: int = Body(embed=True)) -> dict[str, int]:
        return {"number": number}

    @app.get("/test/teapot")
    def teapot() -> None:
        raise ApiError(418, "teapot", {"size": "small"}, {"X-Test": "yes"})

    @app.get("/test/crash")
    def crash() -> None:
        raise RuntimeError("the secret name of a player")

    return app


@pytest.fixture
def client() -> Iterator[TestClient]:
    # The client raises what the application lets out: a crash must not get that far, or the server
    # would log its traceback.
    with TestClient(app_without_database(), base_url=SITE, headers={"Origin": SITE}) as test_client:
        yield test_client


def error_of(response: httpx2.Response) -> dict[str, Any]:
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message_key", "details"}
    assert body["error"]["message_key"] == f"errors.{body['error']['code']}"
    error: dict[str, Any] = body["error"]
    return error


def test_api_errors_use_the_format(client: TestClient) -> None:
    response = client.get("/test/teapot")
    assert response.status_code == 418
    assert response.headers["x-test"] == "yes"
    error = error_of(response)
    assert error["code"] == "teapot"
    assert error["details"] == {"size": "small"}


def test_an_unknown_route_uses_the_format(client: TestClient) -> None:
    response = client.get("/nothing/here")
    assert response.status_code == 404
    assert error_of(response)["code"] == "not_found"


def test_a_wrong_method_uses_the_format(client: TestClient) -> None:
    response = client.delete("/health")
    assert response.status_code == 405
    assert error_of(response)["code"] == "method_not_allowed"


def test_invalid_input_names_the_field_but_not_the_value(client: TestClient) -> None:
    response = client.post("/test/echo", json={"number": "some-private-value"})
    assert response.status_code == 400
    error = error_of(response)
    assert error["code"] == "invalid_request"
    assert "some-private-value" not in response.text
    assert error["details"]["fields"][0]["field"] == "body.number"


def test_a_crash_hides_everything(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.ERROR, logger="ma_api"):
        response = client.get("/test/crash")
    assert response.status_code == 500
    assert error_of(response)["code"] == "internal"
    assert "secret" not in response.text
    assert response.headers["x-content-type-options"] == "nosniff"
    # The log says what and where, without the message that could quote a stranger's data.
    assert "RuntimeError" in caplog.text
    assert "test_app.py" in caplog.text
    assert "secret" not in caplog.text


def test_security_headers_on_every_response(client: TestClient) -> None:
    for response in (client.get("/nothing/here"), client.get("/test/teapot")):
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["referrer-policy"] == "no-referrer"
        assert response.headers["cache-control"] == "no-store"
        assert "strict-transport-security" not in response.headers


def test_hsts_when_the_site_uses_https() -> None:
    with TestClient(
        app_without_database(site_url="https://example.test"),
        base_url="https://example.test",
    ) as client:
        response = client.get("/nothing/here")
    assert "max-age" in response.headers["strict-transport-security"]


@pytest.mark.parametrize(
    "headers",
    [{"Origin": "http://evil.test"}, {"Origin": "http://testserver.evil.test"}, {"Origin": "null"}],
)
def test_a_change_from_another_site_is_refused(client: TestClient, headers: dict[str, str]) -> None:
    response = client.post("/test/echo", json={"number": 1}, headers=headers)
    assert response.status_code == 403
    assert error_of(response)["code"] == "bad_origin"
    assert response.headers["cache-control"] == "no-store"


def test_a_change_without_an_origin_is_refused() -> None:
    with TestClient(app_without_database(), base_url=SITE) as client:
        response = client.post("/test/echo", json={"number": 1})
    assert response.status_code == 403


def test_a_change_from_the_site_goes_through(client: TestClient) -> None:
    assert client.post("/test/echo", json={"number": 1}).json() == {"number": 1}


def test_reads_do_not_need_an_origin() -> None:
    with TestClient(app_without_database(), base_url=SITE) as client:
        assert client.get("/nothing/here").status_code == 404


def test_health_reports_a_database_down(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 503
    assert error_of(response)["code"] == "unavailable"
    # Nothing about the database's address or the reason.
    assert "127.0.0.1" not in response.text


def test_documentation_only_in_development() -> None:
    with TestClient(app_without_database(), base_url=SITE) as client:
        assert client.get(f"{PREFIX}/openapi.json").status_code == 200
        assert client.get("/api/docs").status_code == 200
    with TestClient(app_without_database(production=True), base_url=SITE) as client:
        assert client.get(f"{PREFIX}/openapi.json").status_code == 404
        assert client.get("/api/docs").status_code == 404
