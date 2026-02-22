#!/usr/bin/env bash
set -euo pipefail

# Visual Verification Pipeline
# Runs deterministic visual tests and reports machine-readable PASS/FAIL.
# Usage: ./scripts/verify-visual.sh [--update-snapshots]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

UPDATE_FLAG=""
if [[ "${1:-}" == "--update-snapshots" ]]; then
  UPDATE_FLAG="--update-snapshots"
  echo "Mode: updating golden reference images"
fi

echo "========================================"
echo "  Visual Verification Pipeline"
echo "========================================"
echo ""
echo "Config:"
echo "  Viewport:  1440x900"
echo "  DPR:       2 (Retina)"
echo "  Scheme:    dark"
echo "  Project:   visual"
echo ""

RESULT=0
npx playwright test tests/visual/constellation.spec.ts \
  --project=visual \
  --reporter=list \
  $UPDATE_FLAG 2>&1 || RESULT=$?

echo ""
echo "========================================"

if [ $RESULT -eq 0 ]; then
  echo "  RESULT: PASS"
  echo "========================================"
  echo ""
  echo "All visual assertions passed."
  echo "Run 'npx playwright show-report' for the full HTML report."
else
  echo "  RESULT: FAIL"
  echo "========================================"
  echo ""
  echo "Visual assertions failed."
  echo ""
  echo "Diff images:  test-results/"
  echo "HTML report:  npx playwright show-report"
  echo ""
  echo "If the visual change is intentional, regenerate baselines:"
  echo "  ./scripts/verify-visual.sh --update-snapshots"
fi

exit $RESULT
