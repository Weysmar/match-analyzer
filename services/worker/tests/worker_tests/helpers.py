"""What the tests of the `parse` job need. Everything here is made up."""

import json
import stat
import sys
from pathlib import Path
from typing import Any

from ma_worker.store import StoreError, TooLargeError

REPLAY = b"\x00\x00\x00\x00TAGame.Replay_Soccar_TA\x00 some bytes"


def header(**fields: Any) -> dict[str, Any]:
    """A valid `header.json`."""
    document: dict[str, Any] = {
        "schema_version": 1,
        "parser_version": "0.1.1",
        "game_build": "260918.75141.528314",
        "build_id": 1,
        "changelist": 2,
        "replay_version": {"major": 868, "minor": 34, "net": 12},
        "game_class": "TAGame.Replay_Soccar_TA",
        "match_guid": "A-MATCH-GUID",
        "replay_id": "A-REPLAY-ID",
        "map": "a_map",
        "played_at": "2026-11-01T20:00:00Z",
        "played_at_source": "epoch",
        "duration_s": 300.0,
        "match_type": "Online",
        "playlist": None,
        "team_size": 1,
        "score": {"blue": 1, "orange": 0},
        "goals": [{"frame": 100, "time_s": 12.5, "player_name": "Blue One", "team": 0}],
        "players": [
            player("Blue One", 0, "steam", "1001", goals=1),
            player("Orange One", 1, "epic", "abc"),
        ],
    }
    return document | fields


def player(
    name: str, team: int | None, platform: str, platform_id: str | None, **fields: Any
) -> Any:
    return {
        "platform": platform,
        "platform_id": platform_id,
        "name": name,
        "team": team,
        "score": 100,
        "goals": 0,
        "assists": 0,
        "saves": 0,
        "shots": 0,
        "is_bot": False,
    } | fields


def member(
    index: int,
    name: str,
    team: int,
    platform: str,
    platform_id: str | None,
    *,
    anonymized: bool = False,
) -> dict[str, Any]:
    return {
        "player_idx": index,
        "platform": platform,
        "platform_id": platform_id,
        "name": name,
        "team": team,
        "anonymized": anonymized,
    }


def events(**fields: Any) -> dict[str, Any]:
    """A valid `events.json`, for the players of `header()`."""
    document: dict[str, Any] = {
        "schema_version": 1,
        "parser_version": "0.1.1",
        "fps": None,
        "playlist_id": 13,
        "duration_s": 300.0,
        "arena_out_of_bounds": False,
        "roster": [
            member(0, "Blue One", 0, "steam", "1001"),
            member(1, "Orange One", 1, "epic", "abc"),
        ],
        "goals": [
            {
                "frame": 100,
                "time_s": 12.5,
                "team": 0,
                "player_idx": 0,
                "score_blue": 1,
                "score_orange": 0,
            }
        ],
        "demolitions": [
            {
                "frame": 50,
                "time_s": 5.0,
                "attacker_idx": 1,
                "victim_idx": 0,
                "x": 0.0,
                "y": 0.0,
                "z": 17.0,
            }
        ],
        "pad_pickups": [],
        "unresolved_pad_pickups": 0,
        "stat_events": [],
    }
    return document | fields


class MemoryStore:
    """The object store, in a dictionary."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.broken: set[str] = set()

    def _check(self, operation: str) -> None:
        if operation in self.broken:
            raise StoreError(operation)

    def size(self, key: str) -> int | None:
        self._check("size")
        body = self.objects.get(key)
        return None if body is None else len(body)

    def download(self, key: str, destination: Path, max_bytes: int) -> None:
        self._check("download")
        if key not in self.objects:
            raise StoreError(key)
        if len(self.objects[key]) > max_bytes:
            raise TooLargeError(key)
        destination.write_bytes(self.objects[key])

    def upload(self, source: Path, key: str, content_type: str) -> None:
        self._check("upload")
        self.objects[key] = source.read_bytes()

    def copy(self, source_key: str, key: str) -> None:
        self._check("copy")
        if source_key not in self.objects:
            raise StoreError(source_key)
        self.objects[key] = self.objects[source_key]

    def delete(self, key: str) -> None:
        self._check("delete")
        self.objects.pop(key, None)


class FakeParser:
    """A program standing in for `rl-parse`, run through the real sandbox. It writes the prepared
    files, or ends with the prepared code, and counts its runs. Reading frames fails by default, as
    on a replay of a mode the parser does not read."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.path = folder / "fake-rl-parse"
        self.document = folder / "document.json"
        self.exit_code = folder / "exit-code"
        self.runs = folder / "runs"
        self.events_document = folder / "events-document.json"
        self.frames_code = folder / "frames-code"
        self.frames_behavior = folder / "frames-behavior"
        self.set_header(header())
        self.set_frames_exit_code(12)
        self.path.write_text(
            f"""#!{sys.executable}
import os
import signal
import sys
import time
from pathlib import Path

with open({str(self.runs)!r}, "a") as runs:
    runs.write(" ".join(sys.argv[1:]) + "\\n")
if "--frames" in sys.argv:
    behavior = Path({str(self.frames_behavior)!r})
    action = behavior.read_text() if behavior.exists() else ""
    if action == "hang":
        time.sleep(300)
    if action == "kill":
        os.kill(os.getpid(), signal.SIGKILL)
    code = Path({str(self.frames_code)!r})
    if code.exists():
        sys.exit(int(code.read_text()))
    folder = Path(sys.argv[sys.argv.index("--output-dir") + 1])
    if action != "no-frames":
        (folder / "frames.parquet").write_bytes(b"a parquet file")
    (folder / "events.json").write_bytes(Path({str(self.events_document)!r}).read_bytes())
    sys.exit(0)
code = Path({str(self.exit_code)!r})
if code.exists():
    sys.exit(int(code.read_text()))
target = sys.argv[sys.argv.index("--output") + 1]
Path(target).write_bytes(Path({str(self.document)!r}).read_bytes())
""",
            encoding="utf-8",
        )
        self.path.chmod(self.path.stat().st_mode | stat.S_IEXEC)

    def set_header(self, document: dict[str, Any]) -> None:
        self.document.write_text(json.dumps(document), encoding="utf-8")

    def set_raw_output(self, content: bytes) -> None:
        self.document.write_bytes(content)

    def set_exit_code(self, code: int | None) -> None:
        if code is None:
            self.exit_code.unlink(missing_ok=True)
        else:
            self.exit_code.write_text(str(code), encoding="utf-8")

    def set_events(self, document: dict[str, Any]) -> None:
        """Reading frames now works, and gives this."""
        self.events_document.write_text(json.dumps(document), encoding="utf-8")
        self.set_frames_exit_code(None)

    def set_raw_events(self, content: bytes) -> None:
        self.events_document.write_bytes(content)
        self.set_frames_exit_code(None)

    def set_frames_exit_code(self, code: int | None) -> None:
        if code is None:
            self.frames_code.unlink(missing_ok=True)
        else:
            self.frames_code.write_text(str(code), encoding="utf-8")

    def set_frames_signal(self, _: int) -> None:
        self.frames_behavior.write_text("kill", encoding="utf-8")

    def set_frames_hang(self) -> None:
        self.frames_behavior.write_text("hang", encoding="utf-8")

    def set_no_frames_file(self) -> None:
        self.frames_behavior.write_text("no-frames", encoding="utf-8")

    def run_count(self) -> int:
        if not self.runs.exists():
            return 0
        return len(self.runs.read_text(encoding="utf-8").splitlines())
