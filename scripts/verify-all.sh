#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "[verify] running repo-level checks..."

python3 scripts/check-public-repo-hygiene.py
./scripts/scan-secrets.sh

echo "[verify] backend tests..."
(
  cd backend
  uv sync --frozen --extra dev --extra research
  uv run arena --help >/dev/null
  uv run pytest -q
)

echo "[verify] backend package build..."
uv build --project backend

echo "[verify] bounded invocation/reservation lifecycle model..."
uv run --project backend python scripts/check-lifecycle-model.py

echo "[verify] trace audit smoke..."
TRACE_AUDIT_OUT="$(mktemp)"
cleanup() {
  rm -f "$TRACE_AUDIT_OUT"
}
trap cleanup EXIT

uv run --project backend python scripts/trace-audit.py \
  --input backend/tests/fixtures/trace_audit/sample_runs.json \
  > "$TRACE_AUDIT_OUT"

echo "[verify] protocol artifact validation..."
uv run --project backend python scripts/validate-protocol-artifacts.py

echo "[verify] scientific preregistration readiness..."
uv run --project backend python scripts/validate-scientific-preregistration.py

echo "[verify] Protocol v1 schema generation..."
uv run --project backend python scripts/generate-protocol-v1-schemas.py --check

echo "[verify] Harness Mechanism Atlas generation and semantic validation..."
uv run --project backend python scripts/generate-harness-mechanism-atlas.py --check
uv run --project backend python scripts/validate-harness-mechanism-atlas.py --release-digest release/harness-mechanism-atlas-v1.digest.json

echo "[verify] persistence-v1 scale validation..."
uv run --project backend python scripts/scale/validate_v1_scale.py --check

echo "[verify] release tooling tests..."
uv run --project backend python -m unittest discover -s scripts/tests -p 'test_*.py'

echo "[verify] release bundle hygiene audit..."
uv run --project backend python scripts/check-release-bundle.py --check

echo "[verify] frontier package validation..."
uv run --project backend python scripts/validate-frontier-package.py

echo "[verify] prior-art positioning validation..."
uv run --project backend python scripts/check-prior-art-positioning.py --check

echo "[verify] benchmark evidence validation..."
uv run --project backend python scripts/check-benchmark-evidence.py

echo "[verify] benchmark leakage audit..."
uv run --project backend python scripts/check-benchmark-leakage.py --check

echo "[verify] research integrity validation..."
uv run --project backend python scripts/validate-research-integrity.py

echo "[verify] human calibration packet validation..."
uv run --project backend python scripts/check-human-calibration.py --check

echo "[verify] external validation audit..."
uv run --project backend python scripts/check-external-validation.py --check

echo "[verify] live benchmark readiness preflight..."
uv run --project backend python scripts/check-live-benchmark-readiness.py --check

echo "[verify] live evidence audit..."
uv run --project backend python scripts/check-live-evidence.py --check

echo "[verify] local-runtime evidence custody..."
uv run --project backend python scripts/check-local-runtime-evidence.py

echo "[verify] Hugging Face package manifest..."
uv run --project backend python scripts/check-huggingface-package.py --check

echo "[verify] public claim-boundary validation..."
uv run --project backend python scripts/check-claim-boundaries.py

echo "[verify] docs link sanity..."
uv run --project backend python scripts/check-doc-links.py

echo "[verify] documentation visual asset freshness..."
uv run --project backend python scripts/check-doc-visual-assets.py --check

echo "[verify] sample report freshness..."
uv run --project backend python scripts/generate-sample-report.py --check

echo "[verify] release manifest freshness..."
uv run --project backend python scripts/generate-release-manifest.py --check

echo "[verify] frontend lint/test/build..."
(
  cd frontend
  CI=true npx -y pnpm@10 install --frozen-lockfile
  npx -y pnpm@10 lint
  npx -y pnpm@10 test
  npx -y pnpm@10 build
)

echo "[verify] PASS"
