#!/usr/bin/env bash
set -Eeu -o pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_BASE="${TMPDIR:-/tmp}"
if [[ ! -d "$TMP_BASE" || ! -w "$TMP_BASE" ]]; then
  TMP_BASE="/tmp"
fi
if [[ ! -d "$TMP_BASE" || ! -w "$TMP_BASE" ]]; then
  echo "A writable TMPDIR or /tmp is required for isolated release-smoke outputs." >&2
  exit 1
fi
UV_CACHE_DIR="${UV_CACHE_DIR:-$TMP_BASE/scaffold-arena-uv-cache}"
UV_BIN="${ARENA_SMOKE_UV_BIN:-uv}"

run_viewport() {
  local viewport="$1"
  local run_root backend_pid backend_port frontend_pid frontend_port capture_dir sqlite_path artifact_root backend_log frontend_log
  run_root="$(mktemp -d "$TMP_BASE/scaffold-arena-real-offline-${viewport}.XXXXXX")"
  capture_dir="$run_root/captures"
  sqlite_path="$run_root/state/arena.sqlite3"
  artifact_root="$run_root/state/protocol-v1-artifacts"
  backend_log="$run_root/backend.log"
  frontend_log="$run_root/frontend.log"
  frontend_port="${REAL_OFFLINE_DEMO_FRONTEND_PORT:-$((20000 + RANDOM % 10000))}"
  mkdir -p "$capture_dir" "$artifact_root"

  cleanup_backend() {
    if [[ -n "${backend_pid:-}" ]] && kill -0 "$backend_pid" 2>/dev/null; then
      kill "$backend_pid" 2>/dev/null || true
      wait "$backend_pid" 2>/dev/null || true
    fi
    if [[ -n "${backend_port:-}" ]] && curl --fail --silent "http://127.0.0.1:${backend_port}/health" >/dev/null 2>&1; then
      echo "owned backend port ${backend_port} remained reachable after shutdown" >&2
      return 1
    fi
  }

  cleanup_frontend() {
    if [[ -n "${frontend_pid:-}" ]] && kill -0 "$frontend_pid" 2>/dev/null; then
      kill "$frontend_pid" 2>/dev/null || true
      wait "$frontend_pid" 2>/dev/null || true
    fi
    if [[ -n "${frontend_port:-}" ]] && curl --fail --silent "http://127.0.0.1:${frontend_port}/" >/dev/null 2>&1; then
      echo "owned frontend port ${frontend_port} remained reachable after shutdown" >&2
      return 1
    fi
  }

  cleanup_all() {
    local cleanup_status=0
    cleanup_frontend || cleanup_status=1
    cleanup_backend || cleanup_status=1
    return "$cleanup_status"
  }

  cleanup_on_failure() {
    local exit_status=$?
    trap - ERR INT TERM
    cleanup_all || true
    exit "$exit_status"
  }

  cleanup_on_signal() {
    local exit_status="$1"
    trap - ERR INT TERM
    cleanup_all || true
    exit "$exit_status"
  }

  echo "[real-offline-demo] ${viewport} output: ${run_root}"
  (
    cd "$run_root"
    exec env PYTHONPATH="$ROOT_DIR/backend${PYTHONPATH:+:$PYTHONPATH}" UV_CACHE_DIR="$UV_CACHE_DIR" SQLITE_PATH="$sqlite_path" PROTOCOL_V1_ARTIFACT_ROOT="$artifact_root" \
      "$UV_BIN" run --project "$ROOT_DIR/backend" arena serve --host 127.0.0.1 --port 0 --enable-offline-demo >"$backend_log" 2>&1
  ) &
  backend_pid=$!
  trap cleanup_on_failure ERR
  trap 'cleanup_on_signal 130' INT
  trap 'cleanup_on_signal 143' TERM

  for _ in $(seq 1 60); do
    if ! kill -0 "$backend_pid" 2>/dev/null; then
      cat "$backend_log" >&2
      return 1
    fi
    backend_port="$(sed -nE 's#.*http://127[.]0[.]0[.]1:([0-9]+).*#\1#p' "$backend_log" | tail -n 1)"
    if [[ -n "$backend_port" ]] && curl --fail --silent --show-error "http://127.0.0.1:${backend_port}/health" >/dev/null; then
      break
    fi
    sleep 1
  done
  if [[ -z "${backend_port:-}" ]] || ! curl --fail --silent --show-error "http://127.0.0.1:${backend_port}/health" >/dev/null; then
    cat "$backend_log" >&2
    return 1
  fi
  test -s "$sqlite_path"

  (
    cd "$ROOT_DIR/frontend"
    exec env VITE_API_PROXY_TARGET="http://127.0.0.1:${backend_port}" \
      ./node_modules/.bin/vite --host 127.0.0.1 --port "$frontend_port" --strictPort >"$frontend_log" 2>&1
  ) &
  frontend_pid=$!

  for _ in $(seq 1 60); do
    if ! kill -0 "$frontend_pid" 2>/dev/null; then
      cat "$frontend_log" >&2
      return 1
    fi
    if curl --fail --silent --show-error "http://127.0.0.1:${frontend_port}/" >/dev/null; then
      break
    fi
    sleep 1
  done
  if ! curl --fail --silent --show-error "http://127.0.0.1:${frontend_port}/" >/dev/null; then
    cat "$frontend_log" >&2
    return 1
  fi

  if ! (
    cd "$ROOT_DIR/frontend"
    RUN_REAL_OFFLINE_DEMO=1 \
      REAL_OFFLINE_DEMO_VIEWPORT="$viewport" \
      REAL_OFFLINE_DEMO_CAPTURE_DIR="$capture_dir" \
      REAL_OFFLINE_DEMO_BACKEND_URL="http://127.0.0.1:${backend_port}" \
      PLAYWRIGHT_BASE_URL="http://127.0.0.1:${frontend_port}" \
      PLAYWRIGHT_EXTERNAL_WEB_SERVER=1 \
      CI=true npx -y pnpm@10 exec playwright test --project=offline-demo --grep "at ${viewport} width"
  ); then
    cleanup_all || true
    trap - ERR INT TERM
    return 1
  fi

  test -s "$capture_dir/offline-demo-${viewport}.png"
  test -s "$capture_dir/offline-demo-${viewport}.png.provenance.json"
  test -s "$capture_dir/offline-demo-analysis-${viewport}.csv"
  cleanup_all
  trap - ERR INT TERM
  echo "[real-offline-demo] ${viewport} PASS; retained captures and provenance at ${run_root}"
}

run_viewport desktop
run_viewport mobile
