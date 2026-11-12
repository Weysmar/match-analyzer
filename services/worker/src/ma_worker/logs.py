"""The worker's logs (T9.9 of docs/PLAN.md): text on a workstation, one JSON object per line in
production (`LOG_FORMAT=json`), for the host to collect and search.

A log line names matches, jobs, uploads and game builds by their ids, never a player: what a replay
holds about other players stays out (section 11 of CLAUDE.md). The fields a caller gives through
`extra` (`FIELDS`) become keys of the object; an exception is told by its type, not its text.
"""

import json
import logging
import sys
from datetime import UTC, datetime

FIELDS = ("event", "job_id", "job_kind", "match_id", "upload_id", "build", "status", "code")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        line: dict[str, object] = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in FIELDS:
            value = record.__dict__.get(field)
            if value is not None:
                line[field] = str(value)
        if record.exc_info and record.exc_info[0] is not None:
            line["error"] = record.exc_info[0].__name__
        return json.dumps(line, ensure_ascii=False)


def configure(level: str = "INFO", format_name: str = "text") -> None:
    """One handler on the root logger, to the standard output."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        JsonFormatter()
        if format_name.strip().lower() == "json"
        else logging.Formatter("%(levelname)s:%(name)s:%(message)s")
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.strip().upper() or "INFO")
