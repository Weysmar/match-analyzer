"""The API's logs (T9.9 of docs/PLAN.md): text on a workstation, one JSON object per line in
production (`LOG_FORMAT=json`); uvicorn's own logs go the same way.

No personal data in a log line (section 11 of CLAUDE.md). The access log keeps the method, the path
and the status: never the client's address, nor the query string, where the return from Steam
carries the player's SteamID. The fields a caller gives through `extra` (`FIELDS`) become keys of
the object; an exception is told by its type, not its text.
"""

import json
import logging
from datetime import UTC, datetime
from typing import Any

FIELDS = ("event", "code", "status")
_ACCESS = "uvicorn.access"


def _access(record: logging.LogRecord) -> dict[str, object] | None:
    """uvicorn's access line, as (client, method, path, version, status): without the first, and
    without the query string."""
    if record.name != _ACCESS or not isinstance(record.args, tuple) or len(record.args) != 5:
        return None
    _client, method, path, _version, status = record.args
    return {"method": str(method), "path": str(path).split("?", 1)[0], "status": int(str(status))}


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        access = _access(record)
        message = (
            f"{access['method']} {access['path']} {access['status']}"
            if access
            else record.getMessage()
        )
        return f"{record.levelname}:{record.name}:{message}"


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        access = _access(record)
        line: dict[str, object] = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "logger": record.name,
        }
        if access:
            line |= {"message": f"{access['method']} {access['path']} {access['status']}", **access}
        else:
            line["message"] = record.getMessage()
            for field in FIELDS:
                value = record.__dict__.get(field)
                if value is not None:
                    line[field] = str(value)
        if record.exc_info and record.exc_info[0] is not None:
            line["error"] = record.exc_info[0].__name__
        return json.dumps(line, ensure_ascii=False)


def uvicorn_config(level: str = "INFO", format_name: str = "text") -> dict[str, Any]:
    """The `log_config` given to uvicorn: its loggers and the API's, through one handler."""
    level = level.strip().upper() or "INFO"
    formatter = JsonFormatter if format_name.strip().lower() == "json" else TextFormatter
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {"main": {"()": f"{formatter.__module__}.{formatter.__qualname__}"}},
        "handlers": {
            "out": {
                "class": "logging.StreamHandler",
                "formatter": "main",
                "stream": "ext://sys.stdout",
            }
        },
        "root": {"handlers": ["out"], "level": level},
        "loggers": {
            name: {"level": level, "handlers": [], "propagate": True}
            for name in ("uvicorn", "uvicorn.error", _ACCESS)
        },
    }
