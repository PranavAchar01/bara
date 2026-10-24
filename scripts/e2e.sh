#!/usr/bin/env bash
# Live end-to-end run: server + web, then the WebSocket smoke test and the browser test.
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$ROOT/e2e/logs"
mkdir -p "$LOG_DIR" "$ROOT/e2e/screenshots"
SERVER_PID=""
WEB_PID=""
cleanup() {
  trap - EXIT INT TERM
  for pid in $WEB_PID $SERVER_PID; do
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then kill "$pid" 2>/dev/null; fi
  done
  wait 2>/dev/null
}
trap cleanup EXIT
trap 'exit 130' INT TERM

export BARA_SPEED="${BARA_SPEED:-50}"
# Small event log so the resume check hits E_RESUME_GAP (spec 8.8).
export BARA_EVENT_LOG_KEEP="${BARA_EVENT_LOG_KEEP:-10}"

(cd "$ROOT/server" && exec uv run bara-server) >"$LOG_DIR/server.log" 2>&1 &
SERVER_PID=$!
(cd "$ROOT/web" && exec pnpm dev) >"$LOG_DIR/web.log" 2>&1 &
WEB_PID=$!

wait_port() { # host port label pid
  local i
  for i in $(seq 1 120); do
    if ! kill -0 "$4" 2>/dev/null; then echo "e2e: $3 exited early, see $LOG_DIR" >&2; return 1; fi
    if (exec 3<>"/dev/tcp/$1/$2") 2>/dev/null; then return 0; fi
    sleep 0.5
  done
  echo "e2e: timed out waiting for $3 on $1:$2" >&2
  return 1
}
wait_port 127.0.0.1 8790 server "$SERVER_PID" || exit 2
wait_port 127.0.0.1 5173 web "$WEB_PID" || exit 2

status=0
echo "== ws_smoke"
(cd "$ROOT" && uv run --with websockets --with jsonschema --with referencing python e2e/ws_smoke.py) || status=1
echo "== live_ui"
(cd "$ROOT/web" && node "$ROOT/e2e/live_ui.mjs") || status=1
if [ "$status" -eq 0 ]; then echo "E2E: ALL PASS"; else echo "E2E: FAILURES (logs in $LOG_DIR)"; fi
exit "$status"
