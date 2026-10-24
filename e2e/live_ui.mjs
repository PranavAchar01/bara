// Live UI check against the real server (NOT mock mode).
// Run from anywhere: node e2e/live_ui.mjs   (uses playwright from web/node_modules)
import { createRequire } from "node:module";
import { existsSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const require = createRequire(resolve(here, "../web/package.json"));
let chromium;
try {
  ({ chromium } = require("playwright"));
} catch {
  console.error("FAIL  playwright not found in web/node_modules (run: cd web && pnpm install)");
  process.exit(2);
}

const BASE = process.env.BARA_WEB ?? "http://127.0.0.1:5173/";
const PROMPT = "a keyboard"; // exact_keyboard match_prompt
const SHOT_DIR = resolve(here, "screenshots");
mkdirSync(SHOT_DIR, { recursive: true });

const rows = [];
const check = (name, ok, detail = "") => rows.push({ name, ok: Boolean(ok), detail });

async function launch() {
  try {
    return await chromium.launch({ headless: true });
  } catch (err) {
    const fallback = "/opt/pw-browsers/chromium";
    if (existsSync(fallback)) return chromium.launch({ headless: true, executablePath: fallback });
    throw err;
  }
}

const browser = await launch();
const page = await browser.newPage({ viewport: { width: 1600, height: 960 } });
const consoleErrors = [];
const failedReqs = [];
page.on("console", (m) => {
  if (m.type() === "error" && !m.text().startsWith("Failed to load resource")) consoleErrors.push(m.text().slice(0, 200));
});
page.on("pageerror", (e) => consoleErrors.push(`pageerror: ${String(e).slice(0, 200)}`));
page.on("requestfailed", (r) => failedReqs.push(`${r.url()} ${r.failure()?.errorText}`));
page.on("response", (r) => {
  // v0 ships no part meshes yet; the viewport draws bbox placeholders on a GLB 404
  if (r.status() >= 400 && !/\/assets\/.*\.glb$/.test(r.url())) failedReqs.push(`${r.status()} ${r.url()}`);
});

try {
  await page.goto(BASE, { waitUntil: "domcontentloaded" });
  const prompt = page.getByLabel("Prompt");
  await prompt.waitFor({ timeout: 20000 });
  // The prompt box is disabled until the socket says hello.
  await page.waitForFunction(() => {
    const el = document.querySelector('input[aria-label="Prompt"]');
    return el && !el.disabled;
  }, null, { timeout: 20000 });
  check("prompt enabled after hello (live socket)", true);
  check("not in mock mode", !page.url().includes("mock=1"), page.url());

  await prompt.fill(PROMPT);
  await page.getByRole("button", { name: /Build/ }).click();

  // Done = Add part button on the Parts panel is enabled (store status done).
  const addPart = page.locator('section[aria-label="Parts"] button:has-text("Add part")');
  await addPart.waitFor({ timeout: 30000 });
  let done = false;
  try {
    await page.waitForFunction(() => {
      const b = [...document.querySelectorAll('section[aria-label="Parts"] button')]
        .find((x) => x.textContent?.trim() === "Add part");
      return b && !b.disabled;
    }, null, { timeout: 90000 });
    done = true;
  } catch { /* reported below */ }
  check("build reaches done (Add part enabled)", done);

  const rowsCount = await page.locator("section[aria-label=\"Parts\"] .part-row").count();
  check("Parts panel lists rows", rowsCount > 0, `${rowsCount} rows`);

  const canvas = page.locator("canvas").last();
  await canvas.waitFor({ timeout: 15000 });
  // R3F sizes the canvas from a ResizeObserver, so give it a moment after mount
  await page.waitForFunction(() => [...document.querySelectorAll("canvas")].some((c) => c.getBoundingClientRect().width > 200), null, { timeout: 10000 }).catch(() => {});
  const box = await page.evaluate(() => {
    const r = document.querySelector(".viewport")?.getBoundingClientRect();
    return r ? { width: r.width, height: r.height } : null;
  });
  check("3D viewport visible", !!box && box.width > 200 && box.height > 200,
    box ? `${Math.round(box.width)}x${Math.round(box.height)}` : "no box");
  const webgl = await page.evaluate(() => {
    const c = [...document.querySelectorAll("canvas")].pop();
    return !!c && !!(c.getContext("webgl2") || c.getContext("webgl"));
  });
  check("canvas has a WebGL context", webgl);
  // Canvas is not blank: sample pixels via a screenshot of the canvas element.
  await page.waitForTimeout(1500);
  const shot = await canvas.screenshot();
  check("canvas screenshot non-trivial", shot.length > 4000, `${shot.length} bytes`);

  // BOM: top bar export menu lists BOM (CSV) once ready.
  const bomHit = await page.getByRole("button", { name: /Export/ }).first().isVisible().catch(() => false);
  check("BOM export control visible", bomHit);

  await page.screenshot({ path: resolve(SHOT_DIR, "live_done.png"), fullPage: false });
  check("screenshot written e2e/screenshots/live_done.png", true);
  check("no console errors", consoleErrors.length === 0, consoleErrors.slice(0, 2).join(" | "));
  check("no failed network requests", failedReqs.length === 0, failedReqs.slice(0, 3).join(" | "));
} catch (err) {
  check("ui flow completed", false, String(err).split("\n")[0]);
  try {
    await page.screenshot({ path: resolve(SHOT_DIR, "live_failed.png") });
  } catch { /* ignore */ }
} finally {
  await browser.close();
}

const w = Math.max(...rows.map((r) => r.name.length));
for (const r of rows) console.log(`${r.ok ? "PASS" : "FAIL"}  ${r.name.padEnd(w)}  ${r.ok ? "" : r.detail}`);
const failed = rows.filter((r) => !r.ok).length;
console.log(`\n${rows.length - failed}/${rows.length} passed`);
process.exit(failed ? 1 : 0);
