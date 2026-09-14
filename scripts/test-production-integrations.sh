#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
compose_file="$root_dir/compose.integration-test.yml"
project_name="scaffold-arena-integration-$$_${RANDOM}"

find_port() {
  local start="$1"
  local end="$2"
  python3 - "$start" "$end" <<'PY'
import socket
import sys

for port in range(int(sys.argv[1]), int(sys.argv[2]) + 1):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
        try:
            candidate.bind(("127.0.0.1", port))
        except OSError:
            continue
        print(port)
        raise SystemExit(0)
raise SystemExit("no loopback test port is available")
PY
}

export POSTGRES_TEST_PORT="${POSTGRES_TEST_PORT:-$(find_port 55432 55532)}"
export MINIO_TEST_PORT="${MINIO_TEST_PORT:-$(find_port 59000 59100)}"
export TEST_POSTGRES_URL="postgresql+psycopg://arena_integration_runner:arena_integration_local_only@127.0.0.1:${POSTGRES_TEST_PORT}/arena_integration"
export TEST_S3_ENDPOINT_URL="http://127.0.0.1:${MINIO_TEST_PORT}"
export TEST_S3_BUCKET="arena-integration-artifacts"
export TEST_S3_REGION="us-east-1"
export AWS_ACCESS_KEY_ID="arena_integration_access"
export AWS_SECRET_ACCESS_KEY="arena_integration_secret_local_only"
export AWS_EC2_METADATA_DISABLED="true"
export PYTHONHASHSEED="0"

cleanup() {
  local status="$?"
  trap - EXIT INT TERM
  if [[ "$status" -ne 0 ]]; then
    docker compose \
      --project-name "$project_name" \
      --file "$compose_file" \
      ps --all || true
    docker compose \
      --project-name "$project_name" \
      --file "$compose_file" \
      logs --no-color || true
  fi
  docker compose \
    --project-name "$project_name" \
    --file "$compose_file" \
    down --volumes --remove-orphans >/dev/null 2>&1 || true
  exit "$status"
}
trap cleanup EXIT INT TERM

docker info >/dev/null
docker compose \
  --project-name "$project_name" \
  --file "$compose_file" \
  up --detach --wait

cd "$root_dir/backend"
uv run --frozen --extra dev --extra team pytest \
  tests/persistence_v1/test_postgres_parity.py \
  tests/persistence_v1/test_legacy_and_migrations.py::test_postgres_contract_when_configured \
  tests/artifacts_v1/test_s3_minio_integration.py \
  tests/services_v1/test_team_runtime_integration.py \
  -m integration -q
