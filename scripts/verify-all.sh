#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "[verify] running repo-level checks..."

./scripts/scan-secrets.sh

echo "[verify] backend tests..."
(
  cd backend
  uv run pytest -q
)

echo "[verify] trace audit smoke..."
TRACE_AUDIT_OUT="$(mktemp)"
cleanup() {
  rm -f "$TRACE_AUDIT_OUT"
}
trap cleanup EXIT

uv run --project backend python scripts/trace-audit.py \
  --input backend/tests/fixtures/trace_audit/sample_runs.json \
  > "$TRACE_AUDIT_OUT"

echo "[verify] frontend lint/test/build..."
(
  cd frontend
  npx -y pnpm@10 lint
  npx -y pnpm@10 test
  npx -y pnpm@10 build
)

echo "[verify] PASS"
