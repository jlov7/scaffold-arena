#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
compose_file="$root_dir/compose.postgres-test.yml"
project_name="scaffold-arena-pg-$$_${RANDOM}"

find_port() {
  local candidate
  for candidate in $(seq 55432 55532); do
    if ! lsof -nP -iTCP:"$candidate" -sTCP:LISTEN >/dev/null 2>&1; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

export POSTGRES_TEST_PORT="${POSTGRES_TEST_PORT:-$(find_port)}"
export TEST_POSTGRES_URL="postgresql+psycopg://arena_parity_runner:arena_parity_local_only@127.0.0.1:${POSTGRES_TEST_PORT}/arena_parity"

cleanup() {
  docker compose --project-name "$project_name" --file "$compose_file" down --volumes --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

docker info >/dev/null
docker compose --project-name "$project_name" --file "$compose_file" up --detach --wait

cd "$root_dir/backend"
uv run --extra team pytest tests/persistence_v1/test_postgres_parity.py -m integration -q
