// GET /api/engine: the current engine URL.
// The engine runs on Pranav's Mac behind a Cloudflare quick tunnel whose URL changes on every
// start; the engine now sits behind the named tunnel at api.tangible.parts, so the URL is fixed.
// The line below is rewritten by scripts/serve-public.sh; empty means no engine published.
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
