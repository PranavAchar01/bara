// GET /api/engine: the current engine URL.
// The engine runs on Pranav's Mac behind a Cloudflare quick tunnel whose URL changes on every
// start; scripts/serve-public.sh rewrites ENGINE_URL below, which redeploys the site.
// The line below is rewritten by scripts/serve-public.sh; empty means no engine published.
const ENGINE_URL: string = "https://ruled-positive-delhi-univ.trycloudflare.com";

const reply = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", "cache-control": "no-store" },
  });

export function GET(): Response {
  if (!ENGINE_URL) return reply(503, { error: "no engine published" });
  return reply(200, { url: ENGINE_URL });
}
