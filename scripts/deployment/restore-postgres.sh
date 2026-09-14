#!/usr/bin/env bash
set -euo pipefail

mode="dry-run"
input=""
while (($#)); do
  case "$1" in
    --execute) mode="execute" ;;
    --input) input="${2:?missing backup path}"; shift ;;
    --acknowledge-destructive) acknowledged="yes" ;;
    *) echo "usage: $0 --input backup.dump [--execute --acknowledge-destructive]" >&2; exit 64 ;;
  esac
  shift
done

input="${input:?--input is required}"
if [[ "$mode" == "dry-run" ]]; then
  echo "DRY_RUN: would verify $input.sha256 and inspect the backup; no restore was run."
  exit 0
fi
if [[ "${acknowledged:-}" != "yes" ]]; then
  echo "Refusing restore without --acknowledge-destructive." >&2
  exit 64
fi

: "${PROTOCOL_V1_DATABASE_URL:?set via the deployment secret manager}"
shasum -a 256 -c "$input.sha256"
pg_restore --verbose --clean --if-exists --dbname "$PROTOCOL_V1_DATABASE_URL" "$input"
echo "Restore command completed. Independently verify application readiness and evidence integrity before use."
