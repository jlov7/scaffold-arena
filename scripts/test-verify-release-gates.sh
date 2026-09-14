#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GATE="$ROOT_DIR/scripts/verify-release-gates.sh"

set +e
output="$(SCAFFOLD_ARENA_SKIP_PRODUCTION_INTEGRATION=1 bash "$GATE" 2>&1)"
status=$?
set -e

if [[ "$status" -eq 0 ]]; then
  echo "[release-gate-test] FAIL: skip flag returned success" >&2
  exit 1
fi
if [[ "$output" != *"Docker production integration is required for a release PASS"* ]]; then
  echo "[release-gate-test] FAIL: missing refusal message" >&2
  exit 1
fi
if [[ "$output" == *"authoritative repository verification"* ]]; then
  echo "[release-gate-test] FAIL: skip flag reached heavy verification" >&2
  exit 1
fi
if ! rg -Fq './scripts/test-production-integrations.sh' "$GATE"; then
  echo "[release-gate-test] FAIL: required production integration lane is absent" >&2
  exit 1
fi

echo "[release-gate-test] PASS: skip flag fails before heavy checks and Docker lane remains required"
