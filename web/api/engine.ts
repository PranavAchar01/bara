// GET /api/engine: the current engine URL, only for a caller holding the access key.
// The engine runs on Pranav's Mac behind a Cloudflare quick tunnel whose URL changes on every
// start; scripts/serve-public.sh rewrites ENGINE_URL below, which redeploys the site.
// BARA_ACCESS_TOKEN is a Vercel env var holding the same key the engine checks.
import { createHash, timingSafeEqual } from "node:crypto";
// The line below is rewritten by scripts/serve-public.sh; empty means no engine published.
const ENGINE_URL: string = "https://storage-excellent-diamonds-specifically.trycloudflare.com";

const digest = (s: string) => createHash("sha256").update(s).digest();

function keyMatches(got: string | null): boolean {
  const want = process.env.BARA_ACCESS_TOKEN;
  if (!want || !got) return false;
  return timingSafeEqual(digest(got), digest(want));
}

const reply = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", "cache-control": "no-store" },
  });

export function GET(request: Request): Response {
  if (!keyMatches(request.headers.get("x-bara-token"))) return reply(401, { error: "access key required" });
  if (!ENGINE_URL) return reply(503, { error: "no engine published" });
  return reply(200, { url: ENGINE_URL });
}
