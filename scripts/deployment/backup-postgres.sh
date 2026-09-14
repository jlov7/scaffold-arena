#!/usr/bin/env bash
set -euo pipefail

mode="dry-run"
output=""
while (($#)); do
  case "$1" in
    --execute) mode="execute" ;;
    --output) output="${2:?missing output path}"; shift ;;
    *) echo "usage: $0 [--execute] [--output backup.dump]" >&2; exit 64 ;;
  esac
  shift
done

output="${output:-scaffold-arena-$(date -u +%Y%m%dT%H%M%SZ).dump}"
if [[ "$mode" == "dry-run" ]]; then
  echo "DRY_RUN: would run pg_dump to $output and verify its SHA-256; no database command was run."
  exit 0
fi

: "${PROTOCOL_V1_DATABASE_URL:?set via the deployment secret manager}"
pg_dump --format=custom --file "$output" "$PROTOCOL_V1_DATABASE_URL"
shasum -a 256 "$output" > "$output.sha256"
echo "Backup created and SHA-256 recorded. Offsite retention and restore rehearsal remain separate controls."
