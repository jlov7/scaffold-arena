#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "[scan-secrets] checking tracked and untracked non-ignored files for high-risk secret patterns..."

FILES_LIST="$(mktemp)"
FILE_HITS="$(mktemp)"
CONTENT_HITS="$(mktemp)"
cleanup() {
  rm -f "$FILES_LIST" "$FILE_HITS" "$CONTENT_HITS"
}
trap cleanup EXIT

git ls-files -z --cached --others --exclude-standard > "$FILES_LIST"

if tr '\0' '\n' < "$FILES_LIST" | rg -n '(^|/)\.env$|\.pem$|\.key$|id_rsa|credentials' -i >"$FILE_HITS"; then
  echo "[scan-secrets] FAIL: suspicious secret file names found:"
  cat "$FILE_HITS"
  exit 1
fi

PATTERN='(ghp_[A-Za-z0-9]{30,}|gho_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|BEGIN (RSA|EC|OPENSSH|PRIVATE) KEY|api[_-]?key[[:space:]]*[:=][[:space:]]*["'"'"'`][^"'"'"'`]{12,}|token[[:space:]]*[:=][[:space:]]*["'"'"'`][^"'"'"'`]{12,})'

if xargs -0 rg -n --no-heading --no-messages -S "$PATTERN" < "$FILES_LIST" >"$CONTENT_HITS"; then
  echo "[scan-secrets] FAIL: potential secret-like content found:"
  cat "$CONTENT_HITS"
  exit 1
fi

echo "[scan-secrets] PASS: no high-risk patterns found."
