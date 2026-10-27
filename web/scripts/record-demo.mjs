/* global document, HTMLInputElement */
// Records the landing page's hero video: a real build, start to finish, in the real app.
//
//   node scripts/record-demo.mjs [--url http://localhost:5173/] [--prompt "…"] [--out public/landing] [--headed]
//
// Point --url at a dev server: a mock one (VITE_MOCK=1 pnpm dev, replaying spec/fixtures) or one
// that reaches a live engine (BARA_SERVER=auto pnpm dev). The script records from the home page as
// it types the prompt, then through the whole build in the workspace, pulls the exploded
// view open, focuses a part, then encodes bara-demo.mp4 and .webm (1440×900, 30 fps) and a poster
// frame. Pauses longer than half a second (waiting on the engine) are shortened so the video keeps
// moving; nothing else is sped up or edited.
import { createRequire } from "node:module";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

const arg = (name, fallback) => {
  const i = process.argv.indexOf(`--${name}`);
  return i > 0 && process.argv[i + 1] ? process.argv[i + 1] : fallback;
};
const URL = arg("url", "http://localhost:5173/");  // for the live engine: http://127.0.0.1:<port>/?server=http://127.0.0.1:8797
const PROMPT = arg("prompt", "a wireless split keyboard with an OLED");
const OUT = resolve(arg("out", "public/landing"));
const HEADED = process.argv.includes("--headed");
const MAX_HOLD_S = 0.5;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const browser = await chromium.launch({ headless: !HEADED, args: ["--enable-gpu", "--ignore-gpu-blocklist", "--use-angle=metal"] });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
await page.goto(URL);
// The hero is a live control now: wait for the Start building button to be ready (the engine said hello).
const cta = page.locator(".hero-cta");
await cta.waitFor({ state: "visible", timeout: 30000 });
await page.waitForFunction(() => !document.querySelector(".hero-cta")?.hasAttribute("disabled"), null, { timeout: 60000 });
await sleep(800);

// No part maker or part number may appear in the recording: the page text is checked all the way through.
const BRANDS = /gateron|cherry|kailh|mx2a|ec11e?|alps|panasonic|espressif|esp32|rp2040|raspberry|adafruit|sparkfun|seeed|xiao|arduino|stmicro|stm32|nordic|nrf5\d|texas instr|ssd1306|molex|omron|bourns|lcsc|digi-?key|mouser|nintendo|game ?boy/i;
const brandHits = new Set();
const scanBrands = async () => {
  const text = await page.evaluate(() => document.body.innerText).catch(() => "");
  for (const m of text.matchAll(new RegExp(BRANDS.source, "gi"))) brandHits.add(m[0]);
};
let scanning = true;
const scanLoop = (async () => {
  while (scanning) {
    await scanBrands();
    await sleep(400);
  }
})();

const dir = mkdtempSync(join(tmpdir(), "bara-demo-"));
const frames = [];
const cdp = await page.context().newCDPSession(page);
cdp.on("Page.screencastFrame", async (f) => {
  const file = join(dir, `${String(frames.length).padStart(6, "0")}.jpg`);
  writeFileSync(file, Buffer.from(f.data, "base64"));
  frames.push({ file, t: f.metadata.timestamp });
  await cdp.send("Page.screencastFrameAck", { sessionId: f.sessionId }).catch(() => undefined);
});
await cdp.send("Page.startScreencast", { format: "jpeg", quality: 92, maxWidth: 1440, maxHeight: 900, everyNthFrame: 1 });

// The real path: Start building, the intro asks, the prompt is typed, the handoff, the workspace.
await sleep(600);
await cta.click();
const input = page.locator(".ai-field input");
await page.waitForFunction(() => { const i = document.querySelector(".ai-field input"); return i && !i.disabled; }, null, { timeout: 30000 });
await sleep(1800);
await input.click();
await input.pressSequentially(PROMPT, { delay: 55 });
await sleep(500);
await input.press("Enter");
await page.locator(".workspace").waitFor({ timeout: 30000 });
// The video is the hero's backdrop, so it opens on the workspace once the handoff has landed (the intro is the hero itself).
await sleep(1000);
const workspaceFrom = frames.length;

// The build, until done or failed.
// The Stop button is on the prompt bar while a build runs. A slow engine step is capped, so the video keeps moving.
await page
  .waitForFunction(() => !!document.querySelector(".promptbar") && ![...document.querySelectorAll(".promptbar .btn")].some((b) => /stop/i.test(b.textContent ?? "")), null, { timeout: 150000 })
  .catch(() => undefined);
await sleep(6000); // late models land; the agent cheers and flies home

// Pull the exploded view open, slowly, the way a person drags the slider.
const slider = page.locator(".vp-explode input");
if (await slider.count()) {
  for (let v = 0; v <= 1.0001; v += 0.04) {
    await slider.evaluate((el, val) => {
      const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
      set.call(el, String(val));
      el.dispatchEvent(new Event("input", { bubbles: true }));
    }, Math.min(1, v));
    await sleep(60);
  }
  await sleep(4000);
}

// Pull one part out into focus, then put it back.
const rows = page.locator(".leftcol .part-row");
if ((await rows.count()) > 2) {
  await rows.nth(2).click();
  await sleep(4500);
  await page.keyboard.press("Escape");
  await sleep(2500);
}

await cdp.send("Page.stopScreencast");
scanning = false;
await scanLoop;
await scanBrands();
await browser.close();
if (brandHits.size) throw new Error(`brand names on screen: ${[...brandHits].join(", ")}`);
frames.splice(0, workspaceFrom);
if (frames.length < 10) throw new Error(`only ${frames.length} frames recorded`);

// Each frame shows until the next; stalls are capped so the video never sits still for long.
let list = "";
for (let i = 0; i < frames.length; i++) {
  const next = frames[i + 1]?.t ?? frames[i].t + 1 / 30;
  const hold = Math.min(MAX_HOLD_S, Math.max(1 / 60, next - frames[i].t));
  list += `file '${frames[i].file}'\nduration ${hold.toFixed(4)}\n`;
}
list += `file '${frames[frames.length - 1].file}'\n`;
const listFile = join(dir, "frames.txt");
writeFileSync(listFile, list);

mkdirSync(OUT, { recursive: true });
const ff = (...a) => execFileSync("ffmpeg", ["-y", "-loglevel", "error", ...a], { stdio: "inherit" });
const input_ = ["-f", "concat", "-safe", "0", "-i", listFile, "-vf", "fps=30,scale=1440:-2:flags=lanczos,format=yuv420p"];
ff(...input_, "-c:v", "libx264", "-preset", "slow", "-crf", "21", "-movflags", "+faststart", "-an", join(OUT, "bara-demo.mp4"));
ff(...input_, "-c:v", "libvpx-vp9", "-crf", "33", "-b:v", "0", "-row-mt", "1", "-an", join(OUT, "bara-demo.webm"));
// Poster: the finished build, just before the explode starts.
const doneFrame = frames[Math.max(0, Math.floor(frames.length * 0.62))].file;
ff("-i", doneFrame, "-q:v", "3", join(OUT, "bara-demo.jpg"));
rmSync(dir, { recursive: true, force: true });
console.log(`recorded ${frames.length} frames → ${OUT}/bara-demo.{mp4,webm,jpg}`);
