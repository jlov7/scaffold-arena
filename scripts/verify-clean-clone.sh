#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REVISION="$(git -C "$ROOT_DIR" rev-parse --verify HEAD)"
CLONE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/scaffold-arena-clean.XXXXXX")"

cleanup() {
  rm -rf -- "$CLONE_DIR"
}
trap cleanup EXIT

git clone --no-local --quiet "$ROOT_DIR" "$CLONE_DIR"
git -C "$CLONE_DIR" checkout --quiet --detach "$REVISION"

if [[ -n "$(git -C "$CLONE_DIR" status --porcelain)" ]]; then
  echo "[clean-clone] FAIL: checkout is dirty" >&2
  exit 1
fi

echo "[clean-clone] verifying $REVISION"
"$CLONE_DIR/scripts/verify-all.sh"

if [[ -n "$(git -C "$CLONE_DIR" status --porcelain)" ]]; then
  echo "[clean-clone] FAIL: verification changed tracked files" >&2
  git -C "$CLONE_DIR" status --short >&2
  exit 1
fi

echo "[clean-clone] PASS $REVISION"
