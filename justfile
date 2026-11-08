# Run `just` to list recipes. See docs/PLAN.md.

set dotenv-load

parser := "games/rocket-league/parser/Cargo.toml"

default:
    @just --list

# Python and TypeScript dependencies
install:
    uv sync --all-packages --locked
    pnpm install --frozen-lockfile

# Everything CI runs, except the S3 store
check: lint typecheck test

# Lint and format check, no changes
lint:
    uv run ruff check .
    uv run ruff format --check .
    pnpm lint
    cargo fmt --manifest-path {{parser}} --check
    cargo clippy --manifest-path {{parser}} --all-targets -- -D warnings

# Auto-format and auto-fix
fmt:
    uv run ruff check --fix .
    uv run ruff format .
    pnpm fmt
    cargo fmt --manifest-path {{parser}}

# Strict types: mypy and TypeScript
typecheck:
    uv run mypy
    pnpm typecheck

# All tests
test:
    uv run pytest
    pnpm test
    cargo test --manifest-path {{parser}}

# Real replays: parser against subtr-actor, hostile files, Parquet read by polars (minutes)
test-replays: oracle-cache
    cargo build --release --manifest-path {{parser}}
    cargo test --release --manifest-path {{parser}} --test corpus -- --include-ignored --test-threads=4
    uv run pytest -m replays

# The schemas: counter-examples, then the parser's real output on every local replay
test-schemas:
    uv run pytest packages/schemas/tests
    cargo test --manifest-path {{parser}} --test schema
    cargo build --release --manifest-path {{parser}}
    uv run pytest -m replays tests/replays/test_schemas_on_real_output.py

# Update the anonymized header snapshots, after an INTENDED change: review the diff
parser-snapshots:
    UPDATE_SNAPSHOTS=1 cargo test --release --manifest-path {{parser}} --test corpus headers_match -- --include-ignored

# Build the parser's image and run it on a replay's header
parser-image:
    docker build -t match-analyzer/rl-parse:local games/rocket-league/parser
    docker run --rm match-analyzer/rl-parse:local --version
    docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges --tmpfs /out -v "$PWD/tests/fixtures/replays/public/post-eac-ranked-doubles-2026-04-28.replay:/in.replay:ro" --entrypoint sh match-analyzer/rl-parse:local -c 'rl-parse --header --input /in.replay --output /out/header.json && wc -c /out/header.json'

# Start PostgreSQL and S3 for development, and create the bucket (needs a .env)
dev-up:
    docker compose -f compose.dev.yaml up -d --wait
    uv run python scripts/s3_init.py
    uv run ma-db upgrade

# Apply the migrations and set the roles' passwords
db-migrate:
    uv run ma-db upgrade

# Go back to a migration (`base`: everything)
db-downgrade revision:
    uv run ma-db downgrade {{revision}}

# Database tests, each run in a temporary database (needs `just dev-up`)
test-db:
    uv run pytest -m db

# Serve the API on 127.0.0.1:8000, documentation at /api/docs (needs `just dev-up`)
api:
    uv run ma-api

# Tests against PostgreSQL and the S3 store (needs `just dev-up`)
test-s3:
    uv run pytest -m s3

# The site's upload engine against the API and the S3 store (needs `just dev-up` and `just api`)
test-web-it:
    WEB_IT_API_URL=http://127.0.0.1:8000 pnpm --filter @match-analyzer/web exec vitest run test/it

# The whole journey in a browser, FR and EN at 375 px, with a stand-in for Steam (needs `just dev-up`)
test-e2e *args:
    cargo build --release --manifest-path {{parser}}
    pnpm --filter @match-analyzer/web exec playwright install chromium
    scripts/e2e.sh {{args}}

# subtr-actor's statistics for each replay, computed once: the reference of the metrics
oracle-cache:
    cargo build --release --manifest-path {{parser}}
    uv run python tests/fixtures/oracle.py build

# Every metric against subtr-actor on the corpus: counts and differences only, no name
oracle-report: oracle-cache
    uv run pytest -m replays tests/replays/test_metrics_against_oracle.py -q -p no:cacheprovider

# Real replays through the API, the worker, the parser and S3 (needs `just dev-up` and the corpus)
test-pipeline:
    cargo build --release --manifest-path {{parser}}
    uv run pytest -m pipeline

# Run the jobs (needs `just dev-up`)
worker:
    cargo build --release --manifest-path {{parser}}
    PARSER_BIN=games/rocket-league/parser/target/release/rl-parse uv run ma-worker run

# How the job queue is doing, dead jobs included
worker-status:
    uv run ma-worker status

# Stop them; the data volumes are kept
dev-down:
    docker compose -f compose.dev.yaml down

# Check the S3 behavior uploads rely on (T1.4, T9.4)
s3-check:
    uv run python scripts/s3_check.py

# Reprocess obsolete matches: arrives with T7.14
# Queue outdated matches again: --parser-outdated or --analysis-outdated,
# [--build-from X] [--build-to Y] [--dry-run]. The worker then does the work.
reprocess *args:
    cargo build --release --manifest-path {{parser}}
    PARSER_BIN=games/rocket-league/parser/target/release/rl-parse uv run ma-worker reprocess {{args}}

# One pass of the purge now: raw files, files never sent, expired sessions, old counters.
# The worker also runs it every PURGE_EVERY_S seconds.
purge:
    uv run ma-worker purge

# Download the public replays of the manifest
corpus-fetch:
    uv run python tests/fixtures/corpus.py fetch

# Verify the replay corpus against tests/fixtures/manifest.toml
corpus-check:
    uv run python tests/fixtures/corpus.py check

# Spike T0.3: probe every replay in a child process, write spikes/s0-parse/out/parse.jsonl
spike-parse:
    mkdir -p spikes/s0-parse/out
    cargo run --quiet --release --manifest-path spikes/s0-parse/Cargo.toml -- run spikes/s0-parse/out/parse.jsonl 120 tests/fixtures/replays/public tests/fixtures/replays/legacy tests/fixtures/replays/vincent

# Summarize the spike's output, without any name or id
spike-report:
    python3 -I spikes/s0-parse/summary.py spikes/s0-parse/out/parse.jsonl

# T0.8: hand-computed metrics against subtr-actor's stats (slowest replay and copies left out)
spike-oracle:
    #!/usr/bin/env bash
    set -u
    cd spikes/s0-parse
    cargo build --quiet --release
    : > out/oracle.jsonl
    for f in ../../tests/fixtures/replays/public/*.replay ../../tests/fixtures/replays/legacy/*.replay ../../tests/fixtures/replays/vincent/*.replay; do
      [ -e "$f" ] || continue
      case "$f" in *9AC15BE24A56EEF46EF4EEB56A2040A6*|*" - Copie"*) continue ;; esac
      case "$(basename "$f")" in replay-format-201*|replay-format-2020*|old-ballchasing*) continue ;; esac
      timeout 60 target/release/s0-parse oracle "$f" >> out/oracle.jsonl 2>/dev/null || echo "failed: $(basename "$f")"
    done
    python3 -I oracle_summary.py out/oracle.jsonl

# T0.6: phases through a light collector, against the timeline, on one replay
spike-light file:
    cargo run --quiet --release --manifest-path spikes/s0-parse/Cargo.toml -- light {{file}}

# T0.7: count the replays where this Epic account id appears. Prints counts only.
spike-epic account_id:
    cargo run --quiet --release --manifest-path spikes/s0-parse/Cargo.toml -- epic-check {{account_id}} tests/fixtures/replays/vincent tests/fixtures/replays/legacy

# The site, against `just api` (http://localhost:3000)
web:
    pnpm --filter @match-analyzer/web dev

# The site as it runs in production
web-build:
    pnpm --filter @match-analyzer/web build

# The API's description and the site's types, regenerated from the API's code
openapi:
    uv run python scripts/openapi.py
    pnpm --filter @match-analyzer/api-types gen
