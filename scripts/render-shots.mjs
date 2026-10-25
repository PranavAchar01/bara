// Product shots for builds that have none: every finished build in the engine's library, drawn alone (no floor,
// no grid, transparent around it) by the app's own 3D view, cropped to the device and saved as
// <assets>/cache/shots/<build_id>.webp, which the engine then lists as the build's shot_url. New builds get
// theirs on their own (the browser that built one shoots it); this is for older ones, or to redo them all.
// Needs the web dev server and the engine. Run: node scripts/render-shots.mjs [--all] [--assets <dir>] [build_id ...]
// Without --all it only draws builds that have no shot yet.
import { createRequire } from "node:module";
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const require = createRequire(resolve(here, "../web/package.json"));
const { chromium } = require("playwright");

const BASE = (process.env.BARA_WEB ?? "http://localhost:5173/").replace(/\/?$/, "/");
const args = process.argv.slice(2);
const all = args.includes("--all");
const at = args.indexOf("--assets");
const ASSETS = resolve(at >= 0 ? args[at + 1] : resolve(here, "../server/data/assets"));
const only = args.filter((a, i) => a.startsWith("b_") && args[i - 1] !== "--assets");
const OUT = resolve(ASSETS, "cache", "shots");

mkdirSync(OUT, { recursive: true });
const list = await fetch(`${BASE}v1/library`).then((r) => r.json());
const builds = (list.builds ?? []).filter((b) => b.status === "done" && (only.length ? only.includes(b.build_id) : all || !existsSync(resolve(OUT, `${b.build_id}.webp`))));
console.log(`${builds.length} build(s) to draw into ${OUT}`);

const browser = await chromium.launch({ headless: true });
let made = 0;
for (const b of builds) {
  const page = await browser.newPage({ viewport: { width: 1400, height: 1000 }, deviceScaleFactor: 2 });
  try {
    await page.goto(`${BASE}?shot=${b.build_id}`);
    // the page crops itself once fully drawn (web/src/library/shots.ts), the same as a browser finishing a build
    await page.waitForFunction(() => window.__shot === "shot" || window.__shot === "failed", null, { timeout: 120_000 });
    const data = await page.evaluate(() => window.__shotData ?? null);
    if (!data) throw new Error("nothing was drawn");
    writeFileSync(resolve(OUT, `${b.build_id}.webp`), Buffer.from(data.split(",")[1], "base64"));
    made++;
    console.log(`ok   ${b.build_id}  ${b.prompt}`);
  } catch (e) {
    console.log(`skip ${b.build_id}  ${b.prompt}: ${e instanceof Error ? e.message : e}`);
  } finally {
    await page.close();
  }
}
await browser.close();
console.log(`${made} shot(s) written`);
