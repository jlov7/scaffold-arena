#!/usr/bin/env bash
set -euo pipefail

uv run --project backend --extra dev pytest \
  backend/tests/study_packs_v1/test_offline_demo_v1.py \
  backend/tests/integration_v1/test_offline_demo_fixture_chain.py \
  -q
