#!/usr/bin/env bash
set -euo pipefail

output="${1:-artifacts/provenance.json}"
mkdir -p "$(dirname "$output")"
revision="$(git rev-parse HEAD)"
tree_state="$(git status --porcelain | shasum -a 256 | awk '{print $1}')"
generated_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
printf '{"predicate_type":"scaffold-arena.local-build-v1","revision":"%s","worktree_state_sha256":"%s","generated_at":"%s","signing":"HOLD_EXTERNAL"}\n' "$revision" "$tree_state" "$generated_at" > "$output"
echo "Provenance written to $output. No signature or CI attestation was produced."
