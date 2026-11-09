"""The end of step 6: real replays, from the API to the database, through the real parser and the
real object store. Needs `just dev-up` and the corpus: run it with `just test-pipeline`.

Output holds counts only, never a name or an id.
"""

import collections
import gzip
import http.client
import json
import os
import subprocess
import sys
import time
import urllib.parse
import uuid
from collections.abc import Iterator
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx2
import polars as pl
import psycopg
import pytest
from fastapi.testclient import TestClient

from ma_api import sessions
from ma_api.app import create_app
from ma_api.settings import PREFIX
from ma_api.settings import Settings as ApiSettings
from ma_api.stats import METRIC_IDS
from ma_db.testing import Connection, role_url, temporary_database
from ma_schemas import frames_problems, parse_events, problems
from ma_worker import analyze, parse, queue, reparse, reprocess
from ma_worker.runner import Runner
from ma_worker.settings import Settings as WorkerSettings
from ma_worker.store import S3Store

pytestmark = pytest.mark.pipeline

ROOT = Path(__file__).parents[2]
BINARY = ROOT / "games/rocket-league/parser/target/release/rl-parse"
REPLAYS = ROOT / "tests/fixtures/replays"
PUBLIC = REPLAYS / "public"
SITE = "http://testserver"
UPLOADS = f"{PREFIX}/uploads"
MATCHES = f"{PREFIX}/matches"
POLARS_TYPES = {"UInt32": "uint32", "UInt8": "uint8", "Float32": "float32", "Boolean": "boolean"}


def all_replays() -> list[Path]:
    return sorted(REPLAYS.rglob("*.replay"))


def a_replay() -> Path:
    """The smallest public one that is parsed for sure: it runs in CI too."""
    candidates = sorted(PUBLIC.glob("*.replay"), key=lambda path: path.stat().st_size)
    assert candidates, "run `just corpus-fetch`"
    return candidates[len(candidates) // 2]


@pytest.fixture(scope="module")
def admin_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url or not os.environ.get("S3_ENDPOINT"):
        pytest.skip("run `just dev-up`, then `just test-pipeline`")
    return url


@pytest.fixture(scope="module")
def database(admin_url: str) -> Iterator[str]:
    with temporary_database(admin_url) as url:
        yield url


@pytest.fixture(scope="module")
def api_settings(database: str) -> ApiSettings:
    password = os.environ.get("API_DB_PASSWORD", "ma_api_test")
    return ApiSettings(
        database_url=role_url(database, "ma_api", password),
        site_url=SITE,
        session_secret="test-secret",
        s3_endpoint=os.environ["S3_ENDPOINT"],
        s3_public_endpoint=os.environ.get("S3_PUBLIC_ENDPOINT", ""),
        s3_region=os.environ.get("S3_REGION", "us-east-1"),
        s3_bucket=os.environ["S3_BUCKET"],
        s3_access_key_id=os.environ["S3_ACCESS_KEY_ID"],
        s3_secret_access_key=os.environ["S3_SECRET_ACCESS_KEY"],
        rate_upload_anon_per_day=10_000,
        rate_upload_ip_per_day=10_000,
    )


@pytest.fixture(scope="module")
def worker_settings(database: str) -> WorkerSettings:
    password = os.environ.get("WORKER_DB_PASSWORD", "ma_worker_test")
    return WorkerSettings(
        database_url=role_url(database, "ma_worker", password),
        s3_endpoint=os.environ["S3_ENDPOINT"],
        s3_region=os.environ.get("S3_REGION", "us-east-1"),
        s3_bucket=os.environ["S3_BUCKET"],
        s3_access_key_id=os.environ["S3_ACCESS_KEY_ID"],
        s3_secret_access_key=os.environ["S3_SECRET_ACCESS_KEY"],
        parser_bin=str(BINARY),
    )


@pytest.fixture
def conn(database: str) -> Iterator[Connection]:
    with psycopg.connect(database, autocommit=True) as connection:
        connection.execute(
            "TRUNCATE jobs, matches, uploads, users, anonymous_sessions, rate_limit_buckets CASCADE"
        )
        yield connection


def browser(settings: ApiSettings) -> TestClient:
    return TestClient(create_app(settings), base_url=SITE, headers={"Origin": SITE})


def put(url: str, headers: dict[str, str], body: bytes) -> int:
    parts = urllib.parse.urlsplit(url)
    connection = http.client.HTTPConnection(parts.netloc, timeout=30)
    try:
        connection.request("PUT", f"{parts.path}?{parts.query}", body=body, headers=headers)
        return connection.getresponse().status
    finally:
        connection.close()


def get(url: str) -> tuple[int, bytes]:
    """What the browser does with a presigned read URL (its CORS is checked by s3_check)."""
    parts = urllib.parse.urlsplit(url)
    connection = http.client.HTTPConnection(parts.netloc, timeout=30)
    try:
        connection.request("GET", f"{parts.path}?{parts.query}")
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


def send(client: TestClient, body: bytes, name: str = "a.replay") -> str:
    """What the site does: ask for a URL, send the file, say it is done."""
    response = client.post(UPLOADS, json={"files": [{"name": name, "size": len(body)}]})
    assert response.status_code == 201
    created = response.json()["uploads"][0]
    assert put(created["url"], created["headers"], body) == 200
    assert client.post(f"{UPLOADS}/{created['upload_id']}/complete").status_code == 202
    upload_id: str = created["upload_id"]
    return upload_id


def work(settings: WorkerSettings, *, analysis: bool = False) -> int:
    """Runs every queued parse and reparse job, and analyze job if asked, the way the worker's loop
    does. Returns how many."""
    store = S3Store(settings)
    handlers: dict[str, Any] = {
        "parse": lambda c, job: parse.handle(c, job, store, settings),
        "reparse": lambda c, job: reparse.handle(c, job, store, settings),
    }
    if analysis:
        handlers["analyze"] = lambda c, job: analyze.handle(c, job, store, settings)
    with psycopg.connect(settings.database_url, autocommit=True) as connection:
        runner = Runner(
            lambda: psycopg.connect(settings.database_url, autocommit=True),
            handlers,
            "pipeline-test",
            settings.job_timeout_s,
        )
        done = 0
        while runner.run_once(connection):
            done += 1
        return done


def header_of(replay: Path, folder: Path) -> dict[str, Any]:
    output = folder / f"{uuid.uuid4()}.json"
    subprocess.run(
        [BINARY, "--header", "--input", replay, "--output", output],
        check=True,
        capture_output=True,
    )
    document: dict[str, Any] = json.loads(output.read_text(encoding="utf-8"))
    output.unlink()
    return document


def test_a_replay_ends_up_parsed(
    api_settings: ApiSettings,
    worker_settings: WorkerSettings,
    conn: Connection,
    tmp_path: Path,
) -> None:
    replay = a_replay()
    store = S3Store(worker_settings)
    with browser(api_settings) as client:
        upload = send(client, replay.read_bytes())
        assert work(worker_settings) == 1

        item = client.get(f"{UPLOADS}/{upload}").json()
        assert item["status"] == "done"
        match = item["match_id"]
        sheet = client.get(f"{MATCHES}/{match}")
        assert sheet.status_code == 200
        body = sheet.json()
        assert body["match"]["status"] == "parsed"
        assert body["players"]
        assert [item["match_id"] for item in client.get(MATCHES).json()["items"]] == [match]

        # What the database knows of the players never leaves it.
        ids = [
            row[0]
            for row in conn.execute(
                "SELECT platform_id FROM match_players WHERE match_id = %s AND platform_id "
                "IS NOT NULL",
                (match,),
            ).fetchall()
        ]
        for response in (sheet, client.get(MATCHES), client.get(f"{UPLOADS}/{upload}")):
            assert not any(platform_id in response.text for platform_id in ids)

    assert store.size(f"incoming/{upload}") is None
    row = conn.execute(
        "SELECT raw_key, frames_key, events_key FROM matches WHERE id = %s", (match,)
    ).fetchone()
    assert row is not None
    raw_key, frames_key, events_key = row
    assert store.size(raw_key) == replay.stat().st_size

    frames_path = tmp_path / "frames.parquet"
    store.download(frames_key, frames_path, 500_000_000)
    frame = pl.read_parquet(frames_path)
    assert frame.height > 0
    columns = {
        name: POLARS_TYPES[str(kind)]
        for name, kind in frame.schema.items()
        if str(kind) in POLARS_TYPES
    }
    assert frames_problems(columns) == []

    events_path = tmp_path / "events.json"
    store.download(events_key, events_path, 500_000_000)
    events = parse_events(json.loads(events_path.read_text(encoding="utf-8")))
    assert {member["player_idx"] for member in events["roster"]} == {
        player_row[0]
        for player_row in conn.execute(
            "SELECT frames_idx FROM match_players WHERE match_id = %s AND frames_idx IS NOT NULL",
            (match,),
        ).fetchall()
    }
    assert body["match"]["score"]["blue"] is not None

    jobs = conn.execute("SELECT status FROM jobs WHERE kind = 'analyze'").fetchall()
    assert jobs == [("queued",)]


def test_a_corrupted_file_is_rejected(
    api_settings: ApiSettings, worker_settings: WorkerSettings, conn: Connection
) -> None:
    """A real replay with a few flipped bytes: its checksums no longer hold."""
    body = bytearray(a_replay().read_bytes())
    for position in range(len(body) // 2, len(body) // 2 + 16):
        body[position] ^= 0xFF
    with browser(api_settings) as client:
        upload = send(client, bytes(body))
        work(worker_settings)
        item = client.get(f"{UPLOADS}/{upload}").json()
    assert (item["status"], item["rejection"]) == ("rejected", "corrupt")
    assert S3Store(worker_settings).size(f"incoming/{upload}") is None
    assert conn.execute("SELECT count(*) FROM matches").fetchone() == (0,)


def test_a_file_that_is_no_replay_is_rejected(
    api_settings: ApiSettings, worker_settings: WorkerSettings
) -> None:
    with browser(api_settings) as client:
        upload = send(client, b"just some text, with a .replay name")
        work(worker_settings)
        item = client.get(f"{UPLOADS}/{upload}").json()
    assert (item["status"], item["rejection"]) == ("rejected", "not_a_replay")


def test_a_broken_network_ends_up_header_only(
    api_settings: ApiSettings,
    worker_settings: WorkerSettings,
    conn: Connection,
    tmp_path: Path,
) -> None:
    """The header comes from the real parser, the failure is simulated: no replay of the corpus has
    a broken network with sound checksums, which is how a patch would show up."""
    wrapper = tmp_path / "rl-parse"
    wrapper.write_text(
        f'#!/bin/sh\ncase "$1" in --frames) exit 12;; esac\nexec "{BINARY}" "$@"\n',
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    replay = a_replay()
    expected = header_of(replay, tmp_path)["score"]
    with browser(api_settings) as client:
        upload = send(client, replay.read_bytes())
        work(replace(worker_settings, parser_bin=str(wrapper)))
        item = client.get(f"{UPLOADS}/{upload}").json()
        assert item["status"] == "done"
        body = client.get(f"{MATCHES}/{item['match_id']}").json()
    assert body["match"]["status"] == "header_only"
    assert body["match"]["score"] == {"blue": expected["blue"], "orange": expected["orange"]}
    assert conn.execute("SELECT count(*) FROM jobs WHERE kind = 'analyze'").fetchone() == (0,)


def test_two_players_bringing_one_file_share_one_match(
    api_settings: ApiSettings, worker_settings: WorkerSettings, conn: Connection
) -> None:
    body = a_replay().read_bytes()
    with browser(api_settings) as first, browser(api_settings) as second:
        one = send(first, body)
        other = send(second, body)
        assert work(worker_settings) == 2
        statuses = {
            first.get(f"{UPLOADS}/{one}").json()["status"],
            second.get(f"{UPLOADS}/{other}").json()["status"],
        }
        assert statuses == {"done", "duplicate"}
        match = first.get(MATCHES).json()["items"][0]["match_id"]
        assert second.get(MATCHES).json()["items"][0]["match_id"] == match
    assert conn.execute("SELECT count(*) FROM matches").fetchone() == (1,)
    assert conn.execute("SELECT count(*) FROM user_matches").fetchone() == (2,)


def test_a_job_is_taken_up_after_a_worker_dies(
    api_settings: ApiSettings, worker_settings: WorkerSettings, conn: Connection
) -> None:
    with (
        browser(api_settings) as client,
        psycopg.connect(worker_settings.database_url, autocommit=True) as connection,
    ):
        upload = send(client, a_replay().read_bytes())
        # Claimed by a worker that is never heard of again.
        assert queue.claim(connection, "dead-worker", ["parse"]) is not None
        assert work(worker_settings) == 0
        assert client.get(f"{UPLOADS}/{upload}").json()["status"] == "uploaded"
        assert queue.recover(connection, 0) == (1, 0)
        assert work(worker_settings) == 1
        assert client.get(f"{UPLOADS}/{upload}").json()["status"] == "done"


@pytest.mark.parametrize("concurrency", [1, 2])
def test_the_real_worker_process_does_the_job_and_stops_cleanly(
    api_settings: ApiSettings,
    worker_settings: WorkerSettings,
    conn: Connection,
    concurrency: int,
) -> None:
    """The real entry point: settings from the environment, parser lookup, signals."""
    env = os.environ | {
        "WORKER_DATABASE_URL": worker_settings.database_url,
        "PARSER_BIN": str(BINARY),
        "WORKER_CONCURRENCY": str(concurrency),
    }
    with browser(api_settings) as client:
        upload = send(client, a_replay().read_bytes())
        process = subprocess.Popen(
            [sys.executable, "-m", "ma_worker.cli", "run"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            deadline = time.monotonic() + 60
            status = "uploaded"
            while status != "done" and time.monotonic() < deadline:
                time.sleep(0.2)
                status = client.get(f"{UPLOADS}/{upload}").json()["status"]
            assert status == "done"
        finally:
            process.terminate()
            exit_code = process.wait(timeout=20)
    assert exit_code == 0

    report = subprocess.run(
        [sys.executable, "-m", "ma_worker.cli", "status"],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "parse" in report
    assert "done" in report


def test_the_worker_refuses_to_start_without_its_parser(
    worker_settings: WorkerSettings, tmp_path: Path
) -> None:
    env = os.environ | {
        "WORKER_DATABASE_URL": worker_settings.database_url,
        "PARSER_BIN": str(tmp_path / "nothing-here"),
    }
    result = subprocess.run(
        [sys.executable, "-m", "ma_worker.cli", "run"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0
    assert "PARSER_BIN" in result.stderr


def test_a_signed_in_player_sees_the_metrics_of_their_match(
    api_settings: ApiSettings,
    worker_settings: WorkerSettings,
    conn: Connection,
    tmp_path: Path,
) -> None:
    """The whole V1: a real replay, parsed, analyzed, and read back through the API."""
    found = first_with("steam", tmp_path) or first_with("epic", tmp_path)
    if found is None:
        pytest.skip("no player with an id in this corpus")
    replay, account_id = found
    platform = "steam" if first_with("steam", tmp_path) == found else "epic"
    user = conn.execute(
        "INSERT INTO users (display_name) VALUES ('Player') RETURNING id"
    ).fetchone()
    assert user is not None
    conn.execute(
        "INSERT INTO linked_accounts (user_id, provider, provider_account_id) VALUES (%s, %s, %s)",
        (user[0], platform, account_id),
    )
    token = sessions.new_token()
    conn.execute(
        "INSERT INTO auth_sessions (token_hash, user_id, expires_at) VALUES (%s, %s, now() + %s)",
        (sessions.token_hash(token), user[0], timedelta(days=1)),
    )
    with browser(api_settings) as client:
        client.cookies.set("session", token)
        send(client, replay.read_bytes())
        # The parse job, then the analyze job it queued.
        assert work(worker_settings, analysis=True) == 2
        match_id = client.get(MATCHES).json()["items"][0]["match_id"]
        sheet = client.get(f"{MATCHES}/{match_id}").json()
        stats = client.get(f"{PREFIX}/stats/me").json()
        history = client.get(f"{PREFIX}/stats/me/history", params={"metric_id": "boost.avg"})
        view_url = client.get(f"{MATCHES}/{match_id}/view").json()["url"]
    assert sheet["match"]["status"] == "ready"
    # The 2D view, read as the browser does: valid, its players those of the sheet, no name.
    status, packed = get(view_url)
    assert status == 200
    view = json.loads(gzip.decompress(packed))
    assert problems("match2d", view) == []
    assert {player["id"] for player in view["players"]} <= {
        player["match_player_id"] for player in sheet["players"]
    }
    for player in sheet["players"]:
        assert player["name"].encode() not in gzip.decompress(packed)
    assert account_id.encode() not in gzip.decompress(packed)
    me = str(sheet["me"]["match_player_id"])
    # Every metric the API knows, the touches included: the parser finds them on a real replay.
    assert set(sheet["metrics"][me]) == METRIC_IDS
    assert 0 <= sheet["metrics"][me]["boost.avg"] <= 100
    assert sheet["metrics"][me]["touch.count"] > 0
    assert set(sheet["team_metrics"]) == {"0", "1"}
    shares = [sheet["team_metrics"][team]["poss.team_pct"] for team in ("0", "1")]
    assert all(share is not None for share in shares)
    assert 0 < sum(shares) <= 100
    assert stats["matches_count"] == 1
    assert stats["verified_count"] == 1
    assert stats["averages"]["boost.avg"] == pytest.approx(sheet["metrics"][me]["boost.avg"])
    assert [point["match_id"] for point in history.json()["points"]] == [match_id]
    assert account_id not in json.dumps([sheet, stats])
    # Analyzed again, nothing is added.
    rows = conn.execute("SELECT count(*) FROM player_match_metrics").fetchone()
    conn.execute(
        "INSERT INTO jobs (kind, payload) VALUES ('analyze', %s)",
        (json.dumps({"match_id": match_id}),),
    )
    assert work(worker_settings, analysis=True) == 1
    assert conn.execute("SELECT count(*) FROM player_match_metrics").fetchone() == rows

    # As if an older parser had read it: reprocessed, parsed again, analyzed again, the same.
    players = conn.execute(
        "SELECT id FROM match_players WHERE match_id = %s ORDER BY id", (match_id,)
    ).fetchall()
    conn.execute("UPDATE matches SET parser_version = '0.0.1' WHERE id = %s", (match_id,))
    with psycopg.connect(worker_settings.database_url, autocommit=True) as connection:
        version = reprocess.parser_version(worker_settings)
        summary = reprocess.parser_outdated(connection, version)
    assert summary.selected == [uuid.UUID(match_id)]
    assert work(worker_settings, analysis=True) == 2
    with browser(api_settings) as client:
        client.cookies.set("session", token)
        again = client.get(f"{MATCHES}/{match_id}").json()
    assert again["match"]["status"] == "ready"
    assert again["me"] == sheet["me"]
    assert again["metrics"] == sheet["metrics"]
    assert (
        conn.execute(
            "SELECT id FROM match_players WHERE match_id = %s ORDER BY id", (match_id,)
        ).fetchall()
        == players
    )
    row = conn.execute("SELECT parser_version FROM matches WHERE id = %s", (match_id,)).fetchone()
    assert row == (version,)


def first_with(platform: str, folder: Path) -> tuple[Path, str] | None:
    """A replay holding a player of this platform with an id, and that id."""
    for replay in all_replays():
        for player in header_of(replay, folder)["players"]:
            if player["platform"] == platform and player["platform_id"]:
                return replay, player["platform_id"]
    return None


@pytest.mark.parametrize("platform", ["steam", "epic"])
def test_a_signed_in_player_is_identified_and_verified(
    api_settings: ApiSettings,
    worker_settings: WorkerSettings,
    conn: Connection,
    tmp_path: Path,
    platform: str,
) -> None:
    found = first_with(platform, tmp_path)
    if found is None:
        pytest.skip(f"no {platform} player with an id in this corpus")
    replay, account_id = found
    user = conn.execute(
        "INSERT INTO users (display_name) VALUES ('Player') RETURNING id"
    ).fetchone()
    assert user is not None
    conn.execute(
        "INSERT INTO linked_accounts (user_id, provider, provider_account_id) VALUES (%s, %s, %s)",
        (user[0], platform, account_id),
    )
    token = sessions.new_token()
    conn.execute(
        "INSERT INTO auth_sessions (token_hash, user_id, expires_at) VALUES (%s, %s, now() + %s)",
        (sessions.token_hash(token), user[0], timedelta(days=1)),
    )
    with browser(api_settings) as client:
        client.cookies.set("session", token)
        send(client, replay.read_bytes())
        work(worker_settings)
        listed = client.get(MATCHES).json()["items"][0]
        assert listed["verified"] is True
        sheet = client.get(f"{MATCHES}/{listed['match_id']}").json()
    assert sheet["me"]["identity_source"] == "linked_account"
    assert sum(player["is_me"] for player in sheet["players"]) == 1
    assert account_id not in json.dumps(sheet)


def test_the_whole_corpus_goes_through(
    api_settings: ApiSettings,
    worker_settings: WorkerSettings,
    conn: Connection,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """No replay may leave a job dead or an upload stuck, whatever it holds."""
    replays = all_replays()
    with browser(api_settings) as client:
        for replay in replays:
            send(client, replay.read_bytes())
        assert work(worker_settings) == len(replays)
        uploads = httpx2.QueryParams({"limit": 200})
        items: list[dict[str, Any]] = []
        while True:
            page = client.get(UPLOADS, params=uploads).json()
            items += page["items"]
            if page["next_cursor"] is None:
                break
            uploads = uploads.set("cursor", page["next_cursor"])
    statuses = collections.Counter(item["status"] for item in items)
    matches = collections.Counter(
        tuple(row) for row in conn.execute("SELECT status, error_code FROM matches").fetchall()
    )
    dead = conn.execute("SELECT count(*) FROM jobs WHERE status = 'dead'").fetchone()
    with capsys.disabled():
        print(
            f"\ncorpus: {len(replays)} replays, uploads {dict(statuses)}, matches {dict(matches)}"
        )
    assert dead == (0,)
    assert len(items) == len(replays)
    assert set(statuses) <= {"done", "duplicate"}
    assert {status for status, _ in matches} <= {"parsed", "header_only"}
    # The only failure the corpus is known for: replays of a mode the parser does not read.
    assert {error for status, error in matches if status == "header_only"} <= {"unsupported_mode"}
