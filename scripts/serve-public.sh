#!/usr/bin/env bash
# One command to put the engine behind the deployed site:
#   scripts/serve-public.sh          start the engine (with the access key), a Cloudflare quick
#                                    tunnel to it, and publish the tunnel URL to the site
#   scripts/serve-public.sh open     open the deployed site in the browser, already unlocked
#   scripts/serve-public.sh sync     copy the keychain access key to the Vercel env var again
#
# Keys never touch a file: the Anthropic key comes from the keychain item bara-anthropic, the
# access key from bara-access-token (created on first run). Quick tunnels need no account; their
# URL changes on each start, so the script commits it to web/api/engine.ts on GitHub, which
# redeploys the site (about a minute). Ctrl-C stops the engine and the tunnel.
set -euo pipefail

repo="$(cd "$(dirname "$0")/.." && pwd)"
port="${BARA_PORT:-8791}"
site="${BARA_SITE:-https://bara-ivory-five.vercel.app}"
gh_repo="${BARA_GH_REPO:-PranavAchar01/bara}"
pointer=web/api/engine.ts
acct=pranav

access_key() {
  security find-generic-password -a "$acct" -s bara-access-token -w 2>/dev/null
}

sync_vercel() {
  # The Vercel project is linked in the main checkout's .vercel/ (root directory web/).
  local key; key="$(access_key)"
  (cd "${BARA_VERCEL_DIR:-$HOME/helloworld/bara}" &&
    printf %s "$key" | vercel env add BARA_ACCESS_TOKEN production --force --sensitive >/dev/null)
  echo "Vercel env BARA_ACCESS_TOKEN updated (takes effect on the next deploy)."
}

case "${1:-serve}" in
  open)
    open "$site/?key=$(access_key)"
    exit 0
    ;;
  sync)
    sync_vercel
    exit 0
    ;;
  serve) ;;
  *)
    echo "usage: $0 [serve|open|sync]" >&2
    exit 2
    ;;
esac

if ! access_key >/dev/null; then
  security add-generic-password -a "$acct" -s bara-access-token -w "$(openssl rand -hex 24)"
  echo "Created a new access key in the keychain (bara-access-token)."
  sync_vercel
fi

publish() {
  # Rewrite the ENGINE_URL line through the GitHub API, so no local checkout is touched.
  local url="$1" meta sha body
  meta="$(gh api "repos/$gh_repo/contents/$pointer?ref=main")"
  sha="$(jq -r .sha <<<"$meta")"
  body="$(jq -r .content <<<"$meta" | base64 -D |
    sed -E "s#^const ENGINE_URL: string = \".*\";#const ENGINE_URL: string = \"$url\";#")"
  gh api -X PUT "repos/$gh_repo/contents/$pointer" -f message="engine: $url" \
    -f content="$(printf '%s\n' "$body" | base64)" -f sha="$sha" -f branch=main >/dev/null
  echo "Published $url; the site picks it up after its redeploy (about a minute)."
}

log_dir="${TMPDIR:-/tmp}/engine-public"
mkdir -p "$log_dir"
server_pid=""
tunnel_pid=""
cleanup() {
  [ -n "$tunnel_pid" ] && kill "$tunnel_pid" 2>/dev/null || true
  [ -n "$server_pid" ] && kill "$server_pid" 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 0' INT TERM

(
  cd "$repo/server"
  ANTHROPIC_API_KEY="$(security find-generic-password -a "$acct" -s bara-anthropic -w)" \
    BARA_ACCESS_TOKEN="$(access_key)" BARA_MOCK=0 BARA_PORT="$port" \
    BARA_LLM_TIMEOUT_S="${BARA_LLM_TIMEOUT_S:-20}" exec uv run bara-server
) >"$log_dir/server.log" 2>&1 &
server_pid=$!
echo "Engine starting on 127.0.0.1:$port (log: $log_dir/server.log)"
for _ in $(seq 120); do
  curl -fs "http://127.0.0.1:$port/v1/health" >/dev/null 2>&1 && break
  kill -0 "$server_pid" 2>/dev/null || { echo "The engine exited; see $log_dir/server.log" >&2; exit 1; }
  sleep 1
done

while kill -0 "$server_pid" 2>/dev/null; do
  cloudflared tunnel --no-autoupdate --url "http://127.0.0.1:$port" >"$log_dir/tunnel.log" 2>&1 &
  tunnel_pid=$!
  url=""
  for _ in $(seq 60); do
    url="$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' "$log_dir/tunnel.log" | head -1 || true)"
    [ -n "$url" ] && break
    sleep 1
  done
  if [ -n "$url" ]; then
    publish "$url" || echo "Publishing the URL failed; the site still points at the old one." >&2
    echo "Open the app unlocked: $0 open"
  fi
  wait "$tunnel_pid" || true
  echo "cloudflared exited, restarting"
  sleep 3
done
echo "The engine exited; see $log_dir/server.log" >&2
