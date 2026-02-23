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

echo "[verify] frontend lint/test/build..."
(
  cd frontend
  pnpm lint
  pnpm test
  pnpm build
)

echo "[verify] PASS"
