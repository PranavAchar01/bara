// GET /api/engine: the engine URL.
// The engine runs on Pranav's Mac behind the named Cloudflare tunnel at api.tangible.parts.
// scripts/serve-public.sh rewrites the line below only with BARA_QUICK_TUNNEL=1; empty means
// no engine published.
const ENGINE_URL: string = "https://api.tangible.parts";

const reply = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", "cache-control": "no-store" },
  });

export function GET(): Response {
  if (!ENGINE_URL) return reply(503, { error: "no engine published" });
  return reply(200, { url: ENGINE_URL });
}
