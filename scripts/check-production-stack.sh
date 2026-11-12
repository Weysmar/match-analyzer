#!/usr/bin/env bash
# The production stack starts (T9.2 of docs/PLAN.md): compose.yaml with an S3 emulator in place of
# R2 (.github/compose.ci.yaml). The images must exist: `docker compose ... build`, or the CI's.
# The migrations pass, the API reaches its database, the site answers and relays to the API, and the
# worker stays up. Everything is stopped and removed on the way out, volumes included.
# Usage: scripts/check-production-stack.sh
set -euo pipefail
cd "$(dirname "$0")/.."

compose=(docker compose -f compose.yaml -f .github/compose.ci.yaml --env-file .github/ci.env)
trap '"${compose[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true' EXIT

"${compose[@]}" up --detach --no-build --wait-timeout 120

wait_for() {
  local what=$1 url=$2 expected=$3
  for _ in $(seq 1 60); do
    if curl -sf "$url" | grep -q "$expected"; then
      echo "ok: $what"
      return 0
    fi
    sleep 1
  done
  echo "not answering: $what ($url)" >&2
  return 1
}

wait_for "the API reaches PostgreSQL" http://127.0.0.1:8000/health '"status":"ok"'
wait_for "the site serves its home page" http://127.0.0.1:3000/ "<html"
wait_for "the site relays to the API" http://127.0.0.1:3000/api/v1/me '"features"'

migrate=$("${compose[@]}" ps --all --format '{{.Service}} {{.State}} {{.ExitCode}}' | grep '^migrate ')
[[ $migrate == "migrate exited 0" ]] || { echo "migrations: $migrate" >&2; exit 1; }
echo "ok: the migrations passed"

sleep 5
worker=$("${compose[@]}" ps --format '{{.Service}} {{.State}}' | grep '^worker ' || true)
[[ $worker == "worker running" ]] || { echo "worker: ${worker:-gone}" >&2; exit 1; }
echo "ok: the worker stays up"

for service in api worker web; do
  user=$("${compose[@]}" exec -T "$service" id -u)
  [[ $user != 0 ]] || { echo "$service runs as root" >&2; exit 1; }
done
echo "ok: no service runs as root"
