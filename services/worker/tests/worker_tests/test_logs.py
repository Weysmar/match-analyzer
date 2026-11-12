"""The worker's logs (T9.9): one JSON object per line in production, with the fields given."""

import json
import logging

from ma_worker import logs


def record(**extra: object) -> logging.LogRecord:
    made = logging.LogRecord(
        "ma_worker", logging.WARNING, __file__, 1, "match %s: %s", ("m1", "x"), None
    )
    made.__dict__.update(extra)
    return made


def test_a_line_is_a_json_object_with_the_fields_given() -> None:
    line = json.loads(
        logs.JsonFormatter().format(
            record(event="parsed", match_id="m1", build="260424.1", status="header_only", code=7)
        )
    )
    assert line["level"] == "warning"
    assert line["logger"] == "ma_worker"
    assert line["message"] == "match m1: x"
    assert (line["event"], line["match_id"], line["build"]) == ("parsed", "m1", "260424.1")
    assert (line["status"], line["code"]) == ("header_only", "7")
    assert line["time"].endswith("+00:00")


def test_other_attributes_stay_out_and_an_error_is_its_type() -> None:
    try:
        raise ValueError("a value that could be anything")
    except ValueError:
        import sys

        made = record(player_name="someone")
        made.exc_info = sys.exc_info()
    line = json.loads(logs.JsonFormatter().format(made))
    assert "player_name" not in line
    assert line["error"] == "ValueError"
    assert "a value that could be anything" not in json.dumps(line)


def test_configure_sets_one_handler_and_the_format(capsys: object) -> None:
    root = logging.getLogger()
    saved = (list(root.handlers), root.level)
    try:
        logs.configure("debug", "json")
        assert len(root.handlers) == 1
        assert root.level == logging.DEBUG
        assert isinstance(root.handlers[0].formatter, logs.JsonFormatter)
        logs.configure("INFO", "text")
        assert not isinstance(root.handlers[0].formatter, logs.JsonFormatter)
    finally:
        root.handlers, root.level = saved[0], saved[1]
