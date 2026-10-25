// Records a real build in the workspace for the landing hero: web/public/landing/bara-demo.{mp4,webm,jpg}.
// Needs the web dev server and a live engine running. Run: node scripts/record-demo.mjs ["a prompt"]
// Frames come from Chrome's screencast; a frame that sits still is held at most MAX_HOLD so waits (board routing) read as a beat, not a stall.
import { createRequire } from "node:module";
import { execFileSync } from "node:child_process";
import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const require = createRequire(resolve(here, "../web/package.json"));
const { chromium } = require("playwright");

const BASE = process.env.BARA_WEB ?? "http://localhost:5173/";
const PROMPT = process.argv[2] ?? "a macropad with one big knob";
const OUT = resolve(here, "../web/public/landing");
const TMP = resolve(process.env.TMPDIR ?? "/tmp", "bara-demo-frames");
const VIEW = { width: 1440, height: 900 };
const SCALE = 1.5;
const MAX_HOLD = 0.6; // seconds a still frame may last
const TAIL = 8; // seconds to keep filming after the build is done
const SPEED = 1.5;

rmSync(TMP, { recursive: true, force: true });
mkdirSync(TMP, { recursive: true });
mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: VIEW, deviceScaleFactor: SCALE, colorScheme: "light" });
await page.goto(BASE);
await page.waitForSelector(".prompt-input");
// let the socket say hello so the build button is live
await page.waitForTimeout(1500);

await page.waitForTimeout(800);
await page.click(".prompt-input");
await page.keyboard.type(PROMPT, { delay: 55 });
await page.waitForTimeout(400);
await page.keyboard.press("Enter");

// film from the workspace on: the landing page has no place inside its own hero video
await page.waitForSelector(".workspace");
const cdp = await page.context().newCDPSession(page);
const frames = [];
cdp.on("Page.screencastFrame", async (f) => {
  const file = resolve(TMP, `f${String(frames.length).padStart(5, "0")}.jpg`);
  writeFileSync(file, Buffer.from(f.data, "base64"));
  frames.push({ file, t: f.metadata.timestamp });
  await cdp.send("Page.screencastFrameAck", { sessionId: f.sessionId }).catch(() => undefined);
});
await cdp.send("Page.startScreencast", { format: "jpeg", quality: 92, maxWidth: VIEW.width * SCALE, maxHeight: VIEW.height * SCALE, everyNthFrame: 1 });

const started = Date.now();
// Export unlocks only when the build is done
await page.waitForSelector(".panel-toolbar .btn.primary:not([disabled])", { timeout: 300_000 });
console.log(`build took ${Math.round((Date.now() - started) / 1000)} s`);
// the bot keeps walking through the result (board, firmware) for a few seconds after Export unlocks
await page.waitForTimeout(TAIL * 1000);
await cdp.send("Page.stopScreencast");
await page.screenshot({ path: resolve(OUT, "bara-demo.jpg"), type: "jpeg", quality: 85 });
await browser.close();

// concat list: each frame lasts until the next one, capped
let list = "";
for (let i = 0; i < frames.length; i++) {
  const next = frames[i + 1]?.t ?? frames[i].t + 0.5;
  const d = Math.min(MAX_HOLD, Math.max(1 / 60, next - frames[i].t)) / SPEED;
  list += `file '${frames[i].file}'\nduration ${d.toFixed(4)}\n`;
}
list += `file '${frames.at(-1).file}'\n`;
writeFileSync(resolve(TMP, "list.txt"), list);
console.log(`${frames.length} frames`);

const vf = `fps=30,scale=1920:-2:flags=lanczos:out_range=tv,format=yuv420p`;
const input = ["-y", "-f", "concat", "-safe", "0", "-i", resolve(TMP, "list.txt"), "-vf", vf, "-an"];
execFileSync("ffmpeg", [...input, "-c:v", "libx264", "-preset", "slow", "-crf", "24", "-pix_fmt", "yuv420p", "-movflags", "+faststart", resolve(OUT, "bara-demo.mp4")], { stdio: "inherit" });
execFileSync("ffmpeg", [...input, "-c:v", "libvpx-vp9", "-crf", "36", "-b:v", "0", "-row-mt", "1", resolve(OUT, "bara-demo.webm")], { stdio: "inherit" });
