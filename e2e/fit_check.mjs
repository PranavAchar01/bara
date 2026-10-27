// End-to-end check of the fit check in the real app: build a device, measure a space from a photo,
// let the agent judge the fit, approve its proposal, and check again.
// Needs the web dev server and a live engine. Run: BARA_WEB=http://localhost:5173/ node e2e/fit_check.mjs [out_dir]
import { createRequire } from "node:module";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const require = createRequire(resolve(here, "../web/package.json"));
const { chromium } = require("playwright");

const BASE = process.env.BARA_WEB ?? "http://localhost:5173/";
const PROMPT = process.env.FIT_PROMPT ?? "a 2x2 macropad with a volume knob";
const PHOTOS = resolve(here, "../docs/hackathons/opencv26/photos");
const OUT = resolve(process.argv[2] ?? resolve(here, "../docs/hackathons/opencv26/e2e"));
mkdirSync(OUT, { recursive: true });
const log = [];
const note = (k, v) => {
  log.push({ t: new Date().toISOString(), k, v });
  console.log(k, typeof v === "string" ? v : JSON.stringify(v));
};

const browser = await chromium.launch({ headless: true, args: ["--use-angle=metal", "--ignore-gpu-blocklist", "--enable-gpu"] });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
page.setDefaultTimeout(90_000);
page.on("response", async (r) => {
  if (r.url().includes("/v1/vision/fit")) {
    const b = await r.json().catch(() => null);
    if (b) note("fit_response", { status: r.status(), measurement: { ...b.measurement, tried: undefined }, fit: b.fit, action: b.action, message: b.message, steps: b.steps });
  }
});
await page.goto(BASE);
await page.getByText("Connected", { exact: true }).first().waitFor();
for (let i = 0; i < 3 && !(await page.locator(".bot-mic").count()); i++) {
  if (!(await page.locator(".ai-field input").isVisible())) await page.click(".hero-cta", { force: true });
  await page.waitForSelector(".ai-field input");
  await page.fill(".ai-field input", PROMPT);
  await page.click(".ai-send");
  await page.waitForSelector(".bot-mic", { timeout: 30_000 }).catch(() => note("retry_start", i));
}
const t0 = Date.now();
const done = () =>
  page
    .waitForFunction(() => /Done!/.test(document.querySelector(".bot-mic")?.textContent ?? ""), null, { timeout: 420_000 })
    .catch(async (e) => {
      await page.screenshot({ path: resolve(OUT, "fail.png") });
      note("stuck_on", await page.evaluate(() => document.querySelector(".bot-mic")?.textContent ?? document.body.innerText.slice(0, 400)));
      writeFileSync(resolve(OUT, "e2e-log.json"), JSON.stringify(log, null, 1));
      throw e;
    });
await done();
note("build_s", Math.round((Date.now() - t0) / 1000));
await page.waitForTimeout(1500);

async function measure(photo, shot) {
  const wait = page.waitForResponse((r) => r.url().includes("/v1/vision/fit"), { timeout: 90_000 });
  await page.setInputFiles('.side-overlay[aria-label="Fit check"] input[type=file]', resolve(PHOTOS, photo));
  await wait;
  await page.locator(".fit-result").last().waitFor({ state: "attached", timeout: 60_000 }).catch(async (e) => {
    await page.screenshot({ path: resolve(OUT, "fail.png") });
    note("panel_html", await page.evaluate(() => document.querySelector('.side-overlay[aria-label="Fit check"]')?.outerHTML.slice(0, 1500) ?? "no panel"));
    writeFileSync(resolve(OUT, "e2e-log.json"), JSON.stringify(log, null, 1));
    throw e;
  });
  await page.waitForTimeout(400);
  await page.screenshot({ path: resolve(OUT, shot) });
}

await page.click('[aria-label="Fit check"]', { force: true });
await page.waitForSelector('.side-overlay[aria-label="Fit check"]');
await measure("synthetic_no_marker.jpg", "1-no-marker.png");
await measure("synthetic_space_90x60.jpg", "2-too-small-space.png");
const action = page.locator(".fit-result .btn.primary").last();
if (await action.count()) {
  note("approve", await action.innerText());
  await action.click();
  await page.waitForFunction(() => !/Done!/.test(document.querySelector(".bot-mic")?.textContent ?? ""), null, { timeout: 30_000 }).catch(() => {});
  await done();
  await page.waitForTimeout(2000);
  await page.screenshot({ path: resolve(OUT, "3-after-approve.png") });
  if (!(await page.locator('.side-overlay[aria-label="Fit check"]').count())) await page.click('[aria-label="Fit check"]', { force: true });
}
await measure("synthetic_space_90x60.jpg", "4-recheck-same-space.png");
await measure("synthetic_space_160x110.jpg", "5-roomy-space.png");
writeFileSync(resolve(OUT, "e2e-log.json"), JSON.stringify(log, null, 1));
await browser.close();
