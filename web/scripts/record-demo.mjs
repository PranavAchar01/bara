/* global document, HTMLInputElement */
// Records the landing page's hero video: a real build, start to finish, in the real app.
//
//   node scripts/record-demo.mjs [--url http://localhost:5173/] [--prompt "…"] [--out public/landing] [--headed]
//
// Point --url at a dev server: a mock one (VITE_MOCK=1 pnpm dev, replaying spec/fixtures) or one
// that reaches a live engine (BARA_SERVER=auto pnpm dev). The script submits the prompt, records
// the workspace (prompt bar hidden) through the whole build, pulls the exploded view open, focuses
// a part, then encodes bara-demo.mp4 and .webm (1440×900, constant 24 fps, real speed) and a
// poster frame. Nothing is sped up or edited.
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
const URL = arg("url", "http://localhost:5173/");
const PROMPT = arg("prompt", "a wireless split keyboard with an OLED");
const OUT = resolve(arg("out", "public/landing"));
const HEADED = process.argv.includes("--headed");
const FPS = 24;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const browser = await chromium.launch({ headless: !HEADED, args: ["--enable-gpu", "--ignore-gpu-blocklist", "--use-angle=metal"] });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
await page.goto(URL);
const input = page.locator(".prompt-input").first();
await input.waitFor({ state: "visible", timeout: 30000 });
await page.waitForFunction(() => !document.querySelector(".prompt-input")?.hasAttribute("disabled"), null, { timeout: 60000 });
await input.fill(PROMPT);
await input.press("Enter");
await page.locator(".workspace").waitFor({ timeout: 30000 });
// The video is the canvas at work, not the prompt: the docked prompt bar steps out.
await page.addStyleTag({ content: ".centre-bottom .promptbar { visibility: hidden !important; }" });

// Record from the first frame of the workspace.
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


// The build, until done or failed.
await page.waitForFunction(() => /done|failed/i.test(document.querySelector(".status-pill")?.textContent ?? ""), null, { timeout: 240000 });
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
await browser.close();
if (frames.length < 10) throw new Error(`only ${frames.length} frames recorded`);

// Each frame shows for exactly as long as it was on screen, so motion keeps its real speed;
// the encode then samples that at a constant 24 fps.
let list = "";
for (let i = 0; i < frames.length; i++) {
  const next = frames[i + 1]?.t ?? frames[i].t + 1 / FPS;
  const hold = Math.max(0.001, next - frames[i].t);
  list += `file '${frames[i].file}'\nduration ${hold.toFixed(4)}\n`;
}
list += `file '${frames[frames.length - 1].file}'\n`;
const listFile = join(dir, "frames.txt");
writeFileSync(listFile, list);

mkdirSync(OUT, { recursive: true });
const ff = (...a) => execFileSync("ffmpeg", ["-y", "-loglevel", "error", ...a], { stdio: "inherit" });
const input_ = ["-f", "concat", "-safe", "0", "-i", listFile, "-vf", `fps=${FPS},scale=1440:-2:flags=lanczos,format=yuv420p`];
ff(...input_, "-c:v", "libx264", "-preset", "slow", "-crf", "22", "-r", String(FPS), "-movflags", "+faststart", "-an", join(OUT, "bara-demo.mp4"));
ff(...input_, "-c:v", "libvpx-vp9", "-crf", "34", "-b:v", "0", "-r", String(FPS), "-row-mt", "1", "-an", join(OUT, "bara-demo.webm"));
// Poster: the finished build, just before the explode starts.
const doneFrame = frames[Math.max(0, Math.floor(frames.length * 0.62))].file;
ff("-i", doneFrame, "-q:v", "3", join(OUT, "bara-demo.jpg"));
rmSync(dir, { recursive: true, force: true });
console.log(`recorded ${frames.length} frames → ${OUT}/bara-demo.{mp4,webm,jpg}`);
