#!/usr/bin/env bash
# Start the Bara server (:8790) and web dev server (:5173). Ctrl-C stops only these two PIDs.
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
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

(cd "$ROOT/server" && exec uv run bara-server) &
SERVER_PID=$!
(cd "$ROOT/web" && exec pnpm dev) &
WEB_PID=$!
echo "dev: server pid $SERVER_PID, web pid $WEB_PID"
# Exit when either child dies.
while kill -0 "$SERVER_PID" 2>/dev/null && kill -0 "$WEB_PID" 2>/dev/null; do sleep 1; done
echo "dev: a child exited" >&2
