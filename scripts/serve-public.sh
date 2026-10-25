#!/usr/bin/env bash
# One command to put the engine behind the deployed site: start the engine, which the named tunnel
# serves at api.tangible.parts. BARA_QUICK_TUNNEL=1 instead starts a Cloudflare quick tunnel and
# publishes its URL to the site. The engine is open: anyone with the site
# can build on it (and spends the Anthropic key on this Mac).
#
# The Anthropic key comes from the keychain item bara-anthropic and never touches a file. Quick
# tunnels need no account; their URL changes on each start, so the script commits it to
# web/api/engine.ts on GitHub, which redeploys the site (about a minute). Ctrl-C stops the engine
# and the tunnel.
set -euo pipefail

repo="$(cd "$(dirname "$0")/.." && pwd)"
port="${BARA_PORT:-8797}"
pointer=web/api/engine.ts
acct=pranav

publish() {
  # Deploy main with ENGINE_URL rewritten, as the logged-in Vercel CLI user. A commit to main
  # would trigger git deploys that Vercel blocks (the API commit's author is not on the team)
  # while each still counts against the 100 deploys a day of the free plan.
  local url="$1" tree
  tree="$(mktemp -d)"
  git -C "$repo" fetch -q origin main
  git -C "$repo" archive origin/main | tar -x -C "$tree"
  cp -R "$repo/.vercel" "$tree/.vercel"
  sed -i '' -E "s#^const ENGINE_URL: string = \".*\";#const ENGINE_URL: string = \"$url\";#" \
    "$tree/$pointer"
  (cd "$tree" && vercel deploy --prod --yes >/dev/null 2>"$log_dir/vercel.log") || {
    echo "The site deploy failed (see $log_dir/vercel.log); open" \
      "https://bara-ivory-five.vercel.app/?server=$url meanwhile." >&2
    return 1
  }
  echo "Published $url and deployed the site."
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
    ANTHROPIC_WORKSPACE_ID="$(security find-generic-password -a "$acct" -s bara-anthropic-workspace -w 2>/dev/null)" \
    YOU_API_KEY="$(security find-generic-password -a "$acct" -s bara-you -w 2>/dev/null)" \
    OPENAI_API_KEY="$(security find-generic-password -s OPENAI_API_KEY -w 2>/dev/null)" \
    GITHUB_TOKEN="$(gh auth token 2>/dev/null)" \
    BARA_MOCK=0 BARA_PORT="$port" \
    BARA_LLM_TIMEOUT_S="${BARA_LLM_TIMEOUT_S:-60}" exec uv run bara-server
) >"$log_dir/server.log" 2>&1 &
server_pid=$!
echo "Engine starting on 127.0.0.1:$port (log: $log_dir/server.log)"
for _ in $(seq 120); do
  curl -fs "http://127.0.0.1:$port/v1/health" >/dev/null 2>&1 && break
  kill -0 "$server_pid" 2>/dev/null || { echo "The engine exited; see $log_dir/server.log" >&2; exit 1; }
  sleep 1
done

if [ -n "${BARA_QUICK_TUNNEL:-}" ]; then
  while kill -0 "$server_pid" 2>/dev/null; do
    cloudflared tunnel --no-autoupdate --url "http://127.0.0.1:$port" >"$log_dir/tunnel.log" 2>&1 &
    tunnel_pid=$!
    url=""
    for _ in $(seq 60); do
      url="$(grep -a -o 'https://[a-z0-9-]*\.trycloudflare\.com' "$log_dir/tunnel.log" | head -1 || true)"
      [ -n "$url" ] && break
      sleep 1
    done
    if [ -n "$url" ]; then
      publish "$url" || echo "Publishing the URL failed; the site still points at the old one." >&2
      echo "Open the app: https://bara-ivory-five.vercel.app"
    fi
    wait "$tunnel_pid" || true
    echo "cloudflared exited, restarting"
    sleep 3
  done
else
  # The named tunnel (LaunchAgent com.tangible.cloudflared) serves api.tangible.parts, and the
  # site already points there, so nothing is published.
  echo "Open the app: https://tangible.parts"
  wait "$server_pid" || true
fi
echo "The engine exited; see $log_dir/server.log" >&2
