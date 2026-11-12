#!/usr/bin/env bash
# The production stack starts (T9.2 of docs/PLAN.md): compose.yaml with an S3 emulator in place of
# R2 (.github/compose.ci.yaml). The images must exist: `docker compose ... build`, or the CI's.
# The migrations pass, the API reaches its database, the site answers and relays to the API, the
# worker stays up, no service runs as root; and a backup restores into a blank database with every
# table's rows (T9.7). Everything is stopped and removed on the way out, volumes included.
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

for service in api worker web backup; do
  user=$("${compose[@]}" exec -T "$service" id -u)
  [[ $user != 0 ]] || { echo "$service runs as root" >&2; exit 1; }
done
echo "ok: no service runs as root"

# The API's and the worker's logs are JSON objects, one per line (T9.9).
for service in api worker; do
  lines=$("${compose[@]}" logs --no-log-prefix --no-color "$service")
  [[ -n $lines ]] || { echo "$service: no log line" >&2; exit 1; }
  if grep -qv '^{"time": ' <<<"$lines"; then
    echo "$service: a log line is not JSON" >&2
    exit 1
  fi
done
echo "ok: the API and the worker log JSON"

# A backup, then its restore into a blank database: every table has the same rows (T9.7).
sql() { "${compose[@]}" exec -T db psql -U ma_owner -At -c "$2" "$1"; }
sql match_analyzer "INSERT INTO anonymous_sessions (token_hash, expires_at)
  SELECT sha256(n::text::bytea), now() + interval '1 day' FROM generate_series(1, 3) AS n" >/dev/null
"${compose[@]}" run --rm -T backup ma-db backup
"${compose[@]}" exec -T db createdb -U ma_owner restore_check
"${compose[@]}" run --rm -T backup ma-db restore latest \
  --into "postgresql://ma_owner:ci-owner-password@db:5432/restore_check"
tables=$(sql match_analyzer "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY 1")
[[ -n $tables ]] || { echo "no table to compare" >&2; exit 1; }
for table in $tables; do
  before=$(sql match_analyzer "SELECT count(*) FROM \"$table\"")
  after=$(sql restore_check "SELECT count(*) FROM \"$table\"")
  [[ $before == "$after" ]] || { echo "$table: $before rows, $after restored" >&2; exit 1; }
done
[[ $(sql restore_check "SELECT count(*) FROM anonymous_sessions") == 3 ]] \
  || { echo "the test rows did not come back" >&2; exit 1; }
echo "ok: a backup restores into a blank database, $(wc -w <<<"$tables") tables with their rows"
backups=$("${compose[@]}" run --rm -T backup ma-db backups | grep -c '^postgres/')
[[ $backups -ge 2 ]] || { echo "backups: $backups, the service's own at start missing" >&2; exit 1; }
echo "ok: the backup service wrote its own at start"
