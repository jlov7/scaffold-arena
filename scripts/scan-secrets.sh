#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ $# -gt 0 && "$1" == "--root" && $# -eq 2 ]]; then
  ROOT_DIR="$2"
elif [[ $# -eq 0 ]]; then
  ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
else
  echo "usage: $0 [--root REPOSITORY_ROOT]" >&2
  exit 2
fi
cd "$ROOT_DIR"

echo "[scan-secrets] checking tracked and untracked non-ignored files for high-risk secret patterns..."

FILES_LIST="$(mktemp)"
FILE_HITS="$(mktemp)"
CONTENT_HITS="$(mktemp)"
MISSING_FILES="$(mktemp)"
cleanup() {
  rm -f "$FILES_LIST" "$FILE_HITS" "$CONTENT_HITS" "$MISSING_FILES"
}
trap cleanup EXIT

git ls-files -z --cached --others --exclude-standard > "$FILES_LIST"

while IFS= read -r -d '' relative_path; do
  basename="${relative_path##*/}"
  lower_basename="$(printf '%s' "$basename" | tr '[:upper:]' '[:lower:]')"
  lower_relative_path="$(printf '%s' "$relative_path" | tr '[:upper:]' '[:lower:]')"
  if [[ "$lower_basename" != ".env.example" && ( "$lower_basename" == ".env" || "$lower_basename" == .env.* ) ]]; then
    printf '%s\n' "$relative_path" >> "$FILE_HITS"
    continue
  fi
  if [[ "$lower_relative_path" =~ (^|/)(id_rsa|credentials)(/|$) || "$lower_basename" == *.key || "$lower_basename" == *.pem ]]; then
    printf '%s\n' "$relative_path" >> "$FILE_HITS"
    continue
  fi
  if [[ -L "$relative_path" || ! -f "$relative_path" ]]; then
    printf '%s\n' "$relative_path" >> "$MISSING_FILES"
    continue
  fi
  printf '%s\0' "$relative_path" >> "$CONTENT_HITS"
done < "$FILES_LIST"

if [[ -s "$FILE_HITS" ]]; then
  echo "[scan-secrets] FAIL: suspicious secret file names found:"
  sed 's/^/[scan-secrets] FILE: /' "$FILE_HITS"
  exit 1
fi

if [[ -s "$MISSING_FILES" ]]; then
  echo "[scan-secrets] FAIL: tracked candidate paths missing from the worktree:"
  sed 's/^/[scan-secrets] FILE: /' "$MISSING_FILES"
  exit 1
fi

PATTERN='(ghp_[A-Za-z0-9]{30,}|gho_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|BEGIN (RSA|EC|OPENSSH|PRIVATE) KEY|api[_-]?key\s*[:=]\s*["'"'"'`][^"'"'"'`]{12,}|token\s*[:=]\s*["'"'"'`][^"'"'"'`]{12,})'

CONTENT_FILES="$CONTENT_HITS"
CONTENT_HITS="$(mktemp)"
if ! python3 "${SCRIPT_DIR}/scan-secrets.py" --root "$ROOT_DIR" --pattern "$PATTERN" < "$CONTENT_FILES" >"$CONTENT_HITS"; then
  rm -f "$CONTENT_FILES"
  echo "[scan-secrets] FAIL: content scanner could not complete safely." >&2
  exit 2
fi
rm -f "$CONTENT_FILES"

if [[ -s "$CONTENT_HITS" ]]; then
  echo "[scan-secrets] FAIL: potential secret-like content found:"
  sed 's/^/[scan-secrets] MATCH: /' "$CONTENT_HITS"
  exit 1
fi

echo "[scan-secrets] PASS: no high-risk patterns found."
