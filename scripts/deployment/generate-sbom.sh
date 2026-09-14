#!/usr/bin/env bash
set -euo pipefail

output="${1:-artifacts/sbom.cdx.json}"
mkdir -p "$(dirname "$output")"
command -v syft >/dev/null || { echo "HOLD: install Syft outside this repository to generate an SBOM." >&2; exit 69; }
syft "dir:${2:-.}" -o cyclonedx-json > "$output"
echo "SBOM written to $output. Signing and CI attestation remain external HOLDs."
