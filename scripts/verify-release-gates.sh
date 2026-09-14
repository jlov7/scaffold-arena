#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ "${SCAFFOLD_ARENA_SKIP_PRODUCTION_INTEGRATION:-0}" == "1" ]]; then
  echo "[release-gate] refusing SCAFFOLD_ARENA_SKIP_PRODUCTION_INTEGRATION=1: Docker production integration is required for a release PASS" >&2
  exit 2
fi

echo "[release-gate] authoritative repository verification..."
./scripts/verify-all.sh

echo "[release-gate] backend dependency audit..."
uv audit --project backend --frozen

echo "[release-gate] frontend release lanes..."
(
  cd frontend
  pnpm=(npx -y pnpm@10)

  echo "[release-gate] content lint"
  "${pnpm[@]}" test:content

  echo "[release-gate] frontend coverage"
  "${pnpm[@]}" exec vitest run --coverage

  echo "[release-gate] frontend layering"
  "${pnpm[@]}" arch:layers

  echo "[release-gate] frontend performance budget"
  "${pnpm[@]}" perf:budget

  echo "[release-gate] install Playwright Chromium"
  if [[ "$(uname -s)" == "Linux" ]]; then
    "${pnpm[@]}" exec playwright install --with-deps chromium
  else
    "${pnpm[@]}" exec playwright install chromium
  fi

  echo "[release-gate] E2E and accessibility journeys"
  CI=true "${pnpm[@]}" exec playwright test tests/e2e tests/a11y --project=default

  echo "[release-gate] isolated real offline-demo smoke (desktop and mobile)"
  "$ROOT_DIR/scripts/run-real-offline-demo-smoke.sh"

  echo "[release-gate] visual verification"
  CI=true "${pnpm[@]}" verify:visual

  echo "[release-gate] desktop Lighthouse"
  "${pnpm[@]}" perf:lighthouse

  echo "[release-gate] mobile Lighthouse"
  "${pnpm[@]}" perf:lighthouse:mobile

  echo "[release-gate] frontend dependency audit (all dependencies, moderate threshold)"
  "${pnpm[@]}" audit --audit-level moderate
)

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  echo "[release-gate] production integration (Docker available)..."
  ./scripts/test-production-integrations.sh
else
  echo "[release-gate] production integration REQUIRED but Docker daemon/Compose is unavailable" >&2
  exit 1
fi

echo "[release-gate] PASS"
