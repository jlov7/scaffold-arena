#!/usr/bin/env bash
set -euo pipefail

target_path="${1:-/tmp/scaffold-arena-demo}"

uv run --project backend arena demo --path "$target_path"
