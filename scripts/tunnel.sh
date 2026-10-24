#!/usr/bin/env bash
# Keeps a Cloudflare quick tunnel to the local server up. Each time it (re)starts, the new URL is
# written to web/public/server.json and pushed, so the deployed site (?live=1) and
# `BARA_SERVER=auto pnpm dev` pick it up without anyone copying URLs around.
set -u
cd "$(dirname "$0")/.."
port="${BARA_PORT:-8790}"
pointer=web/public/server.json
log="$(mktemp -t bara-tunnel)"

publish() {
  printf '{"url": "%s"}\n' "$1" > "$pointer"
  git pull -q --rebase --autostash origin main || true
  git add "$pointer"
  git commit -q -m "tunnel: $1" -- "$pointer" && git push -q origin main
  echo "published $1"
}

while true; do
  cloudflared tunnel --no-autoupdate --url "http://127.0.0.1:$port" > "$log" 2>&1 &
  pid=$!
  trap 'kill $pid 2>/dev/null; exit 0' INT TERM
  url=""
  for _ in $(seq 60); do
    url="$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' "$log" | head -1)"
    [ -n "$url" ] && break
    sleep 1
  done
  [ -n "$url" ] && publish "$url"
  wait "$pid"
  echo "cloudflared exited, restarting"
  sleep 3
done
