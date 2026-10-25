// Records a real session for the landing hero: web/public/landing/bara-demo.{mp4,webm,jpg}.
// Needs the web dev server and a live engine running. Run: node scripts/record-demo.mjs ["a prompt"]
// It opens Bara from the hero's Build button, and films from Bara asking what's up: a visible cursor clicks
// the field and types the prompt like a person, the build runs in real time, then the cursor turns the
// finished model and explodes it. Frames come from Chrome's screencast; a frame that sits still is held at
// most MAX_HOLD, so a long quiet wait reads as a beat, not a stall.
import { createRequire } from "node:module";
import { execFileSync } from "node:child_process";
import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const require = createRequire(resolve(here, "../web/package.json"));
const { chromium } = require("playwright");

const BASE = process.env.BARA_WEB ?? "http://localhost:5173/";
const PROMPT = process.argv[2] ?? "a 3x4 macropad with a volume knob";
const OUT = resolve(here, "../web/public/landing");
const TMP = resolve(process.env.TMPDIR ?? "/tmp", "bara-demo-frames");
const VIEW = { width: 1440, height: 900 };
const SCALE = 4 / 3; // 1920 x 1200, the size the video is written at
const MAX_HOLD = 0.6; // seconds a still frame may last
const WALK = 7; // seconds the bot walks through the result after the build is done

// A pointer people recognise, drawn into the page: headless Chrome films no cursor of its own.
const CURSOR = `
  addEventListener("DOMContentLoaded", () => {
    const c = document.createElement("div");
    c.id = "demo-cursor";
    c.innerHTML = '<svg width="22" height="28" viewBox="0 0 16 20"><path d="M1.5 1.5v15.2l4.1-3.9 2.7 6.1 2.6-1.1-2.7-6h5.7z" fill="#111" stroke="#fff" stroke-width="1.3" stroke-linejoin="round"/></svg>';
    c.style.cssText = "position:fixed;left:0;top:0;z-index:2147483647;pointer-events:none;transform:translate(-100px,-100px);transition:scale 90ms ease;filter:drop-shadow(0 1px 2px rgb(0 0 0/.35));margin:-2px 0 0 -2px";
    document.documentElement.appendChild(c);
    addEventListener("mousemove", (e) => (c.style.transform = "translate(" + e.clientX + "px," + e.clientY + "px)"), true);
    addEventListener("mousedown", () => (c.style.scale = "0.86"), true);
    addEventListener("mouseup", () => (c.style.scale = "1"), true);
  });
`;

rmSync(TMP, { recursive: true, force: true });
mkdirSync(TMP, { recursive: true });
mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: VIEW, deviceScaleFactor: SCALE, colorScheme: "light" });
await page.addInitScript(CURSOR);
await page.goto(BASE);
await page.waitForSelector(".hero-cta:not([disabled])");
await page.waitForTimeout(800);

/** Glide the pointer somewhere over `ms`, eased, the way a hand moves a mouse. Paced by the clock, not by
 *  step count: while the 3D view renders and is filmed, each move can take far longer than a frame. */
let at = { x: VIEW.width * 0.3, y: VIEW.height * 0.5 };
async function glide(x, y, ms = 700) {
  const from = at;
  const t0 = Date.now();
  for (;;) {
    const t = Math.min(1, (Date.now() - t0) / ms);
    const e = t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2;
    await page.mouse.move(from.x + (x - from.x) * e, from.y + (y - from.y) * e);
    if (t >= 1) break;
    await page.waitForTimeout(12);
  }
  at = { x, y };
}
async function center(sel) {
  const b = await page.locator(sel).first().boundingBox();
  if (!b) throw new Error(`nothing at ${sel}`);
  return { x: b.x + b.width / 2, y: b.y + b.height / 2, b };
}

const cta = await center(".hero-cta");
await page.mouse.move(cta.x, cta.y);
at = { x: cta.x, y: cta.y };
await page.mouse.click(cta.x, cta.y);

// Film from the paper screen on: the hero has no place inside its own video.
await page.waitForSelector(".agent-intro.ph-here");
const cdp = await page.context().newCDPSession(page);
const frames = [];
cdp.on("Page.screencastFrame", async (f) => {
  const file = resolve(TMP, `f${String(frames.length).padStart(5, "0")}.jpg`);
  writeFileSync(file, Buffer.from(f.data, "base64"));
  frames.push({ file, t: f.metadata.timestamp });
  await cdp.send("Page.screencastFrameAck", { sessionId: f.sessionId }).catch(() => undefined);
});
await cdp.send("Page.startScreencast", { format: "jpeg", quality: 92, maxWidth: VIEW.width * SCALE, maxHeight: VIEW.height * SCALE, everyNthFrame: 1 });

// Bara asks; the cursor drifts over to the field and the prompt is typed like a person would.
await page.waitForTimeout(1300);
const field = await center(".ai-field input");
await glide(field.b.x + 60, field.y, 900);
await page.mouse.click(field.b.x + 60, field.y);
await page.keyboard.press("Meta+A");
await page.keyboard.press("Backspace");
await page.waitForTimeout(350);
for (const ch of PROMPT) {
  await page.keyboard.type(ch);
  await page.waitForTimeout(55 + Math.random() * 70 + (ch === " " ? 40 : 0));
}
await page.waitForTimeout(500);
const send = await center(".ai-send");
await glide(send.x, send.y, 500);
await page.mouse.click(send.x, send.y);

// The build, in real time. The cursor steps aside so the bot has the canvas.
await page.waitForSelector(".workspace");
await glide(VIEW.width * 0.62, VIEW.height * 0.86, 900);
const started = Date.now();
await page.waitForSelector(".panel-toolbar .btn.primary:not([disabled])", { timeout: 300_000 });
console.log(`build took ${Math.round((Date.now() - started) / 1000)} s`);
await page.waitForTimeout(WALK * 1000);

// Show it off: turn the model a little, then explode it and let it settle back.
const canvas = await center(".workspace canvas");
await glide(canvas.x - 120, canvas.y + 40, 700);
await page.mouse.down();
await glide(canvas.x + 140, canvas.y + 10, 1800);
await page.mouse.up();
await page.waitForTimeout(600);
// the view options are folded into one button until wanted
const viewBtn = await center(".vp-view-btn");
await glide(viewBtn.x, viewBtn.y, 700);
await page.mouse.click(viewBtn.x, viewBtn.y);
await page.waitForTimeout(400);
const slider = await center('input[aria-label="Explode"]');
const left = slider.b.x + 4;
const right = slider.b.x + slider.b.width - 4;
await glide(left, slider.y, 900);
await page.mouse.down();
await glide(right, slider.y, 1400);
await page.mouse.up();
await page.waitForTimeout(1800);
await page.mouse.down();
await glide(left, slider.y, 1200);
await page.mouse.up();
await glide(VIEW.width * 0.62, VIEW.height * 0.86, 800);
await page.waitForTimeout(1500);

await cdp.send("Page.stopScreencast");
await page.screenshot({ path: resolve(OUT, "bara-demo.jpg"), type: "jpeg", quality: 85 });
await browser.close();

// concat list: each frame lasts until the next one, capped
let list = "";
for (let i = 0; i < frames.length; i++) {
  const next = frames[i + 1]?.t ?? frames[i].t + 0.5;
  const d = Math.min(MAX_HOLD, Math.max(1 / 60, next - frames[i].t));
  list += `file '${frames[i].file}'\nduration ${d.toFixed(4)}\n`;
}
list += `file '${frames.at(-1).file}'\n`;
writeFileSync(resolve(TMP, "list.txt"), list);
console.log(`${frames.length} frames`);

const vf = `fps=30,scale=1920:-2:flags=lanczos:out_range=tv,format=yuv420p`;
const input = ["-y", "-f", "concat", "-safe", "0", "-i", resolve(TMP, "list.txt"), "-vf", vf, "-an"];
execFileSync("ffmpeg", [...input, "-c:v", "libx264", "-preset", "slow", "-crf", "24", "-pix_fmt", "yuv420p", "-color_range", "tv", "-movflags", "+faststart", resolve(OUT, "bara-demo.mp4")], { stdio: "inherit" });
execFileSync("ffmpeg", [...input, "-c:v", "libvpx-vp9", "-crf", "36", "-b:v", "0", "-row-mt", "1", resolve(OUT, "bara-demo.webm")], { stdio: "inherit" });
