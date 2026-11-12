"""The API's logs (T9.9): JSON in production, and an access log without address nor query string."""

import json
import logging
import logging.config

from ma_api import logs

STEAM_RETURN = (
    "/api/v1/auth/steam/return?openid.claimed_id="
    "https%3A%2F%2Fsteamcommunity.com%2Fopenid%2Fid%2F76561190000000000"
)


def access(path: str = STEAM_RETURN) -> logging.LogRecord:
    return logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("203.0.113.7:51234", "GET", path, "1.1", 302),
        None,
    )


def test_the_access_line_has_no_address_nor_query_string() -> None:
    for formatter in (logs.JsonFormatter(), logs.TextFormatter()):
        text = formatter.format(access())
        assert "203.0.113.7" not in text
        assert "76561190000000000" not in text
        assert "openid" not in text
        assert "GET /api/v1/auth/steam/return 302" in text
    line = json.loads(logs.JsonFormatter().format(access("/api/v1/matches")))
    assert (line["method"], line["path"], line["status"]) == ("GET", "/api/v1/matches", 302)


def test_an_api_line_keeps_its_message_and_fields() -> None:
    made = logging.LogRecord(
        "ma_api", logging.INFO, __file__, 1, "steam sign-in refused: %s", ("no_flow",), None
    )
    made.__dict__["event"] = "sign_in_refused"
    line = json.loads(logs.JsonFormatter().format(made))
    assert line["message"] == "steam sign-in refused: no_flow"
    assert line["event"] == "sign_in_refused"


def test_the_uvicorn_config_routes_every_logger_through_one_handler() -> None:
    config = logs.uvicorn_config("info", "json")
    assert config["root"] == {"handlers": ["out"], "level": "INFO"}
    assert config["formatters"]["main"]["()"] == "ma_api.logs.JsonFormatter"
    assert set(config["loggers"]) == {"uvicorn", "uvicorn.error", "uvicorn.access"}
    assert logs.uvicorn_config()["formatters"]["main"]["()"] == "ma_api.logs.TextFormatter"
    root = logging.getLogger()
    saved = (list(root.handlers), root.level)
    try:
        logging.config.dictConfig(config)
        assert isinstance(root.handlers[0].formatter, logs.JsonFormatter)
    finally:
        root.handlers, root.level = saved[0], saved[1]
