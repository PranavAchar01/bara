// Re-shoot every finished build in the library, so each tile's product shot shows the case as the workspace
// draws it today (clear plastic, opaque parts inside, finish, form features). Re-run whenever the case look
// changes. The shot page (?shot=<id>) shares the workspace's DeviceScene, so nothing here draws anything itself.
//
// Usage: node scripts/reshoot-library.mjs [appUrl] [engineUrl] [--ids=b_x,b_y] [--include-failed]
//   appUrl     a served build of web/ (default http://127.0.0.1:4173): python3 -m http.server 4173 --bind 127.0.0.1 -d dist
//   engineUrl  the live engine (default http://127.0.0.1:8797)
// The engine sends no CORS headers, so the browser runs with the page's engine calls go through a CORS-adding route.
// Shots land in the engine's server/data/assets/cache/shots/ (data, not committed). This is heavy work: take
// ~/helloworld/.heavy-lock and run it under `nice -n 19 taskpolicy -b`.
import { chromium } from "/Users/pranav/helloworld/bara/web/node_modules/playwright/index.mjs";
import { existsSync, readdirSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

const args = process.argv.slice(2);
const flag = (name) => args.find((a) => a.startsWith(`--${name}`));
const pos = args.filter((a) => !a.startsWith("--"));
const app = (pos[0] ?? "http://127.0.0.1:4173").replace(/\/$/, "");
const engine = (pos[1] ?? "http://127.0.0.1:8797").replace(/\/$/, "");
const only = flag("ids=")?.slice("--ids=".length).split(",").filter(Boolean);
const includeFailed = !!flag("include-failed");
const PER_SHOT_MS = 120_000;

function findBrowser() {
  const cache = join(homedir(), "Library", "Caches", "ms-playwright");
  const dirs = existsSync(cache) ? readdirSync(cache) : [];
  const candidates = [];
  for (const d of dirs.filter((x) => x.startsWith("chromium-")).sort().reverse()) {
    candidates.push(join(cache, d, "chrome-mac-arm64", "Google Chrome for Testing.app", "Contents", "MacOS", "Google Chrome for Testing"));
    candidates.push(join(cache, d, "chrome-mac", "Chromium.app", "Contents", "MacOS", "Chromium"));
  }
  candidates.push("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome");
  return candidates.find((p) => existsSync(p)) ?? null;
}

const list = await (await fetch(`${engine}/v1/library`)).json();
let builds = list.builds.filter((b) => includeFailed || b.status === "done");
if (only) builds = builds.filter((b) => only.includes(b.build_id));
console.log(`${builds.length} builds to shoot (engine ${engine}, app ${app})`);

const executablePath = findBrowser();
if (!executablePath) throw new Error("No installed Chromium or Chrome found; not downloading one.");
const browser = await chromium.launch({
  executablePath,
  headless: true,
  args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"],
});

const ok = [];
const failed = [];
for (const [i, b] of builds.entries()) {
  const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } });
  await page.route(`${engine}/**`, async (route) => {
    const req = route.request();
    const cors = { "access-control-allow-origin": "*", "access-control-allow-headers": "*", "access-control-allow-methods": "*" };
    if (req.method() === "OPTIONS") return route.fulfill({ status: 204, headers: cors });
    try {
      const r = await fetch(req.url(), { method: req.method(), headers: req.headers(), body: req.postDataBuffer() ?? undefined });
      const headers = { ...cors, "content-type": r.headers.get("content-type") ?? "application/octet-stream" };
      return route.fulfill({ status: r.status, headers, body: Buffer.from(await r.arrayBuffer()) });
    } catch {
      return route.abort();
    }
  });
  try {
    await page.goto(`${app}/?shot=${encodeURIComponent(b.build_id)}&server=${encodeURIComponent(engine)}`, { waitUntil: "domcontentloaded" });
    await page.waitForFunction(() => globalThis.__shot === "shot" || globalThis.__shot === "failed", null, { timeout: PER_SHOT_MS, polling: 400 });
    const data = await page.evaluate(() => (globalThis.__shot === "shot" ? globalThis.__shotData : null));
    if (!data) throw new Error(`page reported no shot (state ${await page.evaluate(() => globalThis.__shot)})`);
    const bytes = Buffer.from(data.split(",")[1], "base64");
    const res = await fetch(`${engine}/v1/library/${encodeURIComponent(b.build_id)}/shot`, { method: "PUT", headers: { "content-type": "image/webp" }, body: bytes });
    if (!res.ok) throw new Error(`engine answered ${res.status}`);
    ok.push(b.build_id);
    console.log(`[${i + 1}/${builds.length}] ${b.build_id} ok (${bytes.length} B)`);
  } catch (err) {
    failed.push({ id: b.build_id, why: String(err.message ?? err).slice(0, 120) });
    console.log(`[${i + 1}/${builds.length}] ${b.build_id} FAILED ${failed.at(-1).why}`);
  } finally {
    await page.close();
  }
}
await browser.close();
console.log(`done: ${ok.length} shot, ${failed.length} failed`);
for (const f of failed) console.log(`  ${f.id}: ${f.why}`);
process.exit(failed.length ? 1 : 0);
