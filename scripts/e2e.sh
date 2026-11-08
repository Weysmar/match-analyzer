#!/usr/bin/env bash
# The end-to-end journey (step 8): the API with a stand-in for Steam (A70), the worker, the built
# site, then Playwright. Needs `just dev-up` (PostgreSQL and the S3 store), the release parser and
# Playwright's Chromium. Each service runs in its own process group, all stopped on the way out.
# Usage: scripts/e2e.sh [playwright arguments]; logs in $E2E_LOGS (default /tmp/ma-e2e).
set -euo pipefail
cd "$(dirname "$0")/.."

set -a
# shellcheck disable=SC1091
. ./.env
set +a
export STEAM_OPENID_URL="http://127.0.0.1:8090/openid/login"
export PARSER_BIN="games/rocket-league/parser/target/release/rl-parse"
export NEXT_TELEMETRY_DISABLED=1
logs="${E2E_LOGS:-/tmp/ma-e2e}"
mkdir -p "$logs"

groups=()
stop() {
  for group in "${groups[@]}"; do kill -- "-$group" 2>/dev/null || true; done
}
trap stop EXIT

start() {
  local name=$1
  shift
  setsid "$@" >"$logs/$name.log" 2>&1 &
  groups+=($!)
}

wait_for() {
  local url=$1
  for _ in $(seq 1 120); do
    curl -sf -o /dev/null "$url" && return 0
    sleep 0.5
  done
  echo "not answering: $url" >&2
  return 1
}

[ -x "$PARSER_BIN" ] || { echo "build the parser first: cargo build --release" >&2; exit 1; }
pnpm --filter @match-analyzer/web build >"$logs/build.log" 2>&1 || { tail -40 "$logs/build.log"; exit 1; }

start steam uv run python scripts/fake_steam.py 8090
start api uv run ma-api
start worker uv run ma-worker run
start web pnpm --filter @match-analyzer/web exec next start -p 3000
wait_for http://127.0.0.1:8000/health
wait_for http://127.0.0.1:3000/

pnpm --filter @match-analyzer/web exec playwright test "$@"
