// Product shots for the library: every finished build in the engine's library, drawn alone (no floor, no grid,
// transparent around it) by the app's own 3D view, cropped to the device and saved as
// <assets>/cache/shots/<build_id>.webp, which the engine then lists as the build's shot_url.
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
/** Output size; the device is centred in it with a margin. */
const W = 1200;
const H = 900;
const PAD = 0.08;

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
    await page.waitForFunction(() => window.__shot === "ready" || window.__shot === "failed", null, { timeout: 120_000 });
    if ((await page.evaluate(() => window.__shot)) !== "ready") throw new Error("the build would not open");
    // crop to the drawn pixels, centre them on a W x H transparent frame, and keep it as WebP
    const data = await page.evaluate(
      ({ W, H, PAD }) => {
        const src = document.querySelector(".shot-stage canvas");
        const probe = document.createElement("canvas");
        probe.width = src.width;
        probe.height = src.height;
        const p = probe.getContext("2d", { willReadFrequently: true });
        p.drawImage(src, 0, 0);
        const px = p.getImageData(0, 0, probe.width, probe.height).data;
        let x0 = probe.width;
        let y0 = probe.height;
        let x1 = -1;
        let y1 = -1;
        for (let y = 0; y < probe.height; y++)
          for (let x = 0; x < probe.width; x++)
            if (px[(y * probe.width + x) * 4 + 3] > 8) {
              if (x < x0) x0 = x;
              if (x > x1) x1 = x;
              if (y < y0) y0 = y;
              if (y > y1) y1 = y;
            }
        if (x1 < 0) return null;
        const w = x1 - x0 + 1;
        const h = y1 - y0 + 1;
        const k = Math.min((W * (1 - 2 * PAD)) / w, (H * (1 - 2 * PAD)) / h);
        const out = document.createElement("canvas");
        out.width = W;
        out.height = H;
        const o = out.getContext("2d");
        o.imageSmoothingQuality = "high";
        o.drawImage(probe, x0, y0, w, h, (W - w * k) / 2, (H - h * k) / 2, w * k, h * k);
        return out.toDataURL("image/webp", 0.9);
      },
      { W, H, PAD },
    );
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
