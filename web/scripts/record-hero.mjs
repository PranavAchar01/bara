/* global document, window, NodeFilter, HTMLInputElement, MutationObserver, MediaRecorder, FileReader */
// Records the landing hero's backdrop: a real build in the real app, captured smoothly and sharp.
//
//   node scripts/record-hero.mjs --url "http://localhost:5492/?mock=1" [--prompt "…"] [--out public/landing]
//
// Why not headless: headless Chromium paces requestAnimationFrame at about 14 fps, so every spring
// and tween in the app ran at that rate and the old take had ~9 unique frames a second. This opens a
// real (off-screen) window, which runs at the display's 60 Hz, at device scale 2 so the 2x hero is
// sharp. Part makers and part numbers are swapped for plain part names in the page text as it renders
// (the hero must not show brand names), and the text is scanned all the way through to prove it.
// Nothing is sped up or edited.
// Run it under the heavy lock (~/helloworld/CLAUDE.md); the encodes run under nice/taskpolicy.
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
const URL = arg("url", "http://localhost:5173/?mock=1");
const PROMPT = arg("prompt", "a wireless split keyboard with an OLED");
const OUT = resolve(arg("out", "public/landing"));
const FPS = 60;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const BRANDS = /gateron|cherry|kailh|mx2a|ec11|alps|panasonic|espressif|esp32|rp2040|raspberry|adafruit|sparkfun|seeed|xiao|arduino|stmicro|stm32|nordic|nrf5\d|ssd13\d\d|sh1106|molex|omron|bourns|lcsc|digi-?key|mouser|nice!?\s?nano|corne|pro micro|atmega|wemos|lilygo|waveshare|\bjst\b|choc\b|nintendo|game ?boy/i;

const browser = await chromium.launch({
  headless: false,
  args: ["--window-position=-3200,0", "--disable-backgrounding-occluded-windows", "--disable-renderer-backgrounding", "--enable-gpu", "--ignore-gpu-blocklist", "--use-angle=metal", "--auto-accept-this-tab-capture", "--mute-audio"],
});
const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 });
// Plain part names in place of makers and part numbers, rewritten in every text node as it appears.
await page.addInitScript(() => {
  const SWAP = [
    [/nice!?\s?nano(\s*v?\d(\.\d)?)?/gi, "Wireless controller"],
    [/pro\s?micro(\s*\(?atmega32u4\)?)?/gi, "Controller board"],
    [/(gateron|cherry|kailh)(\s+(mx2a|mx|box|ks-\d+|pro))?(\s+(yellow|red|brown|blue|black|silver|white|milky\s+yellow))?/gi, "Key switch"],
    [/\bmx2a\b\s*/gi, ""],
    [/\bchoc\b/gi, "low-profile"],
    [/(ssd13\d\d|sh1106)(\s*(oled|display))?/gi, "OLED display"],
    [/nrf52\d*/gi, "wireless chip"],
    [/atmega\s?\d+\w*/gi, "microcontroller"],
    [/ec11e?\w*/gi, "rotary encoder"],
    [/(adafruit|sparkfun|seeed(\s?studio)?|wemos|lilygo|waveshare|arduino|espressif|raspberry\s+pi)\s*/gi, ""],
    [/(xiao|esp32[\w-]*|rp2040|stm32\w*)/gi, "controller"],
    [/\bjst(\s*[a-z]{1,3})?\b/gi, "connector"],
    [/corne(\s*v?\d)?(\s*(chocolate|cherry))?/gi, "split board"],
    [/\s*\(MX\)/g, ""],
  ];
  const fix = (n) => {
    let t = n.nodeValue;
    if (!t) return;
    // the mock-mode pill is a dev marker, not part of the product
    if (t.trim().toLowerCase() === "mock" && n.parentElement) n.parentElement.style.display = "none";
    for (const [re, to] of SWAP) t = t.replace(re, to);
    if (t !== n.nodeValue) n.nodeValue = t;
  };
  const walk = (root) => {
    if (root.nodeType === 3) return fix(root);
    const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let n = w.nextNode(); n; n = w.nextNode()) fix(n);
  };
  const start = () => {
    walk(document.body);
    new MutationObserver((ms) => {
      for (const m of ms) {
        if (m.type === "characterData") fix(m.target);
        else m.addedNodes.forEach(walk);
      }
    }).observe(document.body, { childList: true, subtree: true, characterData: true });
  };
  if (document.body) start();
  else document.addEventListener("DOMContentLoaded", start);
});
await page.goto(URL);
// Tab capture: the compositor's own frames at the display rate, at full device pixels, recorded in the page.
// (CDP screencast tops out near 5 fps at this size.) It needs a user gesture, and it has to start
// before the app boots (later the request fails with InvalidStateError), so it opens on a click at first load.
await page.mouse.click(1100, 160);
const capture = await page.evaluate(async () => {
  const stream = await navigator.mediaDevices.getDisplayMedia({ video: { frameRate: { ideal: 60 }, width: { ideal: 2880 }, height: { ideal: 1800 } }, audio: false, preferCurrentTab: true, selfBrowserSurface: "include" });
  const s = stream.getVideoTracks()[0].getSettings();
  window.__hero = { stream, chunks: [], rec: null };
  return `${s.width}x${s.height} @ ${s.frameRate}`;
});
console.log("tab capture", capture);
const cta = page.locator(".hero-cta");
await cta.waitFor({ state: "visible", timeout: 30000 });
await page.waitForFunction(() => !document.querySelector(".hero-cta")?.hasAttribute("disabled"), null, { timeout: 60000 });
await sleep(800);

const brandHits = new Set();
const scanBrands = async () => {
  const text = await page.evaluate(() => document.body.innerText).catch(() => "");
  for (const m of text.matchAll(new RegExp(BRANDS.source, "gi"))) brandHits.add(m[0]);
};
let scanning = true;
const scanLoop = (async () => {
  while (scanning) {
    await scanBrands();
    await sleep(300);
  }
})();

const dir = mkdtempSync(join(tmpdir(), "bara-hero-"));

const startRec = () =>
  page.evaluate(() => {
    const h = window.__hero;
    h.rec = new MediaRecorder(h.stream, { mimeType: "video/webm;codecs=vp9", videoBitsPerSecond: 40_000_000 });
    h.rec.ondataavailable = (e) => e.data.size && h.chunks.push(e.data);
    h.rec.start(1000);
  });

// The real path: Start building, the intro asks, the prompt is typed, the handoff, the workspace.
await cta.click();
const input = page.locator(".ai-field input");
await page.waitForFunction(() => { const i = document.querySelector(".ai-field input"); return i && !i.disabled; }, null, { timeout: 30000 });
await sleep(1200);
await input.click();
await input.pressSequentially(PROMPT, { delay: 40 });
await sleep(400);
await input.press("Enter");
await page.locator(".workspace").waitFor({ timeout: 30000 });
// The video is the hero's backdrop, so it opens on the workspace once the handoff has landed.
await sleep(900);
await startRec();

// The build, until the Stop button leaves the prompt bar.
await page
  .waitForFunction(() => !!document.querySelector(".promptbar") && ![...document.querySelectorAll(".promptbar .btn")].some((b) => /stop/i.test(b.textContent ?? "")), null, { timeout: 150000 })
  .catch(() => undefined);
await sleep(5000);

// Pull the exploded view open, the way a person drags the slider.
const slider = page.locator(".vp-explode input");
if (await slider.count()) {
  for (let v = 0; v <= 1.0001; v += 0.025) {
    await slider.evaluate((el, val) => {
      const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
      set.call(el, String(val));
      el.dispatchEvent(new Event("input", { bubbles: true }));
    }, Math.min(1, v));
    await sleep(40);
  }
  await sleep(3500);
}

const size = await page.evaluate(
  () =>
    new Promise((done) => {
      const h = window.__hero;
      h.rec.onstop = () => {
        h.blob = new Blob(h.chunks, { type: "video/webm" });
        h.stream.getTracks().forEach((t) => t.stop());
        done(h.blob.size);
      };
      h.rec.stop();
    }),
);
const raw = join(dir, "raw.webm");
const parts = [];
for (let at = 0; at < size; at += 8 << 20) {
  const b64 = await page.evaluate(
    ([a, b]) =>
      new Promise((done) => {
        const r = new FileReader();
        r.onload = () => done(String(r.result).split(",")[1]);
        r.readAsDataURL(window.__hero.blob.slice(a, b));
      }),
    [at, Math.min(size, at + (8 << 20))],
  );
  parts.push(Buffer.from(b64, "base64"));
}
writeFileSync(raw, Buffer.concat(parts));
scanning = false;
await scanLoop;
await scanBrands();
await browser.close();
if (brandHits.size) throw new Error(`brand names on screen: ${[...brandHits].join(", ")}`);
console.log(`raw take ${(size / 1e6).toFixed(1)} MB at ${raw}`);

mkdirSync(OUT, { recursive: true });
const ff = (...a) => execFileSync("nice", ["-n", "19", "taskpolicy", "-b", "ffmpeg", "-y", "-loglevel", "error", ...a], { stdio: "inherit" });
const vf = (w) => ["-vf", `fps=${FPS},scale=${w}:-2:flags=lanczos,format=yuv420p`];
// AV1 at the 2x size for browsers that play it, H.264 High at 1920 for the rest; keyframes every 2 s, faststart.
ff("-i", raw, ...vf(2560), "-c:v", "libsvtav1", "-preset", "5", "-crf", "34", "-g", String(FPS * 2), "-movflags", "+faststart", "-an", join(OUT, "bara-demo.av1.mp4"));
ff("-i", raw, ...vf(1920), "-c:v", "libx264", "-profile:v", "high", "-preset", "slow", "-crf", "21", "-tune", "animation", "-g", String(FPS * 2), "-movflags", "+faststart", "-an", join(OUT, "bara-demo.mp4"));
// The poster is the first frame, so the still and the video's start are the same picture.
ff("-i", raw, "-frames:v", "1", "-vf", "scale=1920:-2:flags=lanczos", "-q:v", "4", join(OUT, "bara-demo.jpg"));
if (!process.argv.includes("--keep")) rmSync(dir, { recursive: true, force: true });
console.log("wrote", OUT);
