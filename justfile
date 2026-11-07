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

# Start PostgreSQL and S3 for development, and create the bucket (needs a .env)
dev-up:
    docker compose -f compose.dev.yaml up -d --wait
    uv run python scripts/s3_init.py

# Stop them; the data volumes are kept
dev-down:
    docker compose -f compose.dev.yaml down

# Check the S3 behavior uploads rely on (T1.4, T9.4)
s3-check:
    uv run python scripts/s3_check.py

# Reprocess obsolete matches: arrives with T7.14
reprocess:
    @echo "not available yet: see T7.14 in docs/PLAN.md" && exit 1

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
