#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "[scan-secrets] checking tracked files for high-risk secret patterns..."

if git ls-files | rg -n '(^|/)\.env$|\.pem$|\.key$|id_rsa|credentials' -i >/tmp/scan_secrets_file_hits.txt; then
  echo "[scan-secrets] FAIL: suspicious secret file names are tracked:"
  cat /tmp/scan_secrets_file_hits.txt
  exit 1
fi

PATTERN='(ghp_[A-Za-z0-9]{30,}|gho_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|BEGIN (RSA|EC|OPENSSH|PRIVATE) KEY|api[_-]?key[[:space:]]*[:=][[:space:]]*["'"'"'`][^"'"'"'`]{12,}|token[[:space:]]*[:=][[:space:]]*["'"'"'`][^"'"'"'`]{12,})'

if git ls-files | xargs rg -n --no-heading -S "$PATTERN" >/tmp/scan_secrets_content_hits.txt; then
  echo "[scan-secrets] FAIL: potential secret-like content found:"
  cat /tmp/scan_secrets_content_hits.txt
  exit 1
fi

echo "[scan-secrets] PASS: no high-risk patterns found in tracked files."
