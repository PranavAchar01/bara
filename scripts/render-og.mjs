// The tangible.parts link preview: renders scripts/og/scene.html frame by frame into a looping MP4 (og:video,
// which iMessage plays inline) and a still PNG (og:image), both under web/public/og/.
// Also a 3:2 GIF of the same loop for the Devpost thumbnail (web/public/og/tangible-parts-devpost.gif).
// Run: node scripts/render-og.mjs
import { createRequire } from "node:module";
import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const require = createRequire(resolve(here, "../web/package.json"));
const { chromium } = require("playwright");

const FPS = 30;
const out = resolve(here, "../web/public/og");
mkdirSync(out, { recursive: true });
const frames = mkdtempSync(join(tmpdir(), "og-frames-"));

const browser = await chromium.launch();
async function shoot(w, h, dir, fps) {
  const page = await browser.newPage({ viewport: { width: w, height: h } });
  await page.goto(`${pathToFileURL(resolve(here, "og/scene.html")).href}?w=${w}&h=${h}`, { waitUntil: "networkidle" });
  await page.evaluate(() => document.fonts.ready);
  const n = Math.round((await page.evaluate(() => window.LOOP)) * fps);
  mkdirSync(dir, { recursive: true });
  for (let i = 0; i < n; i++) {
    await page.evaluate((t) => window.render(t), i / fps);
    await page.screenshot({ path: join(dir, `f${String(i).padStart(4, "0")}.png`) });
  }
  return { page, n };
}
const { page, n } = await shoot(1200, 630, frames, FPS);
// the still: Bara looking straight out, before anything happens
await page.evaluate(() => window.render(0.3));
await page.screenshot({ path: join(out, "tangible-parts.png") });
const gifFrames = join(frames, "gif");
await shoot(1200, 800, gifFrames, 20);
await browser.close();

execFileSync("ffmpeg", ["-y", "-loglevel", "error", "-framerate", String(FPS), "-i", join(frames, "f%04d.png"),
  "-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p", "-crf", "22", "-preset", "slow", "-movflags", "+faststart", "-an",
  join(out, "tangible-parts.mp4")]);
execFileSync("ffmpeg", ["-y", "-loglevel", "error", "-framerate", "20", "-i", join(gifFrames, "f%04d.png"),
  "-vf", "scale=900:600:flags=lanczos,split[a][b];[a]palettegen=max_colors=32:stats_mode=diff[p];[b][p]paletteuse=dither=none:diff_mode=rectangle",
  "-loop", "0", join(out, "tangible-parts-devpost.gif")]);
rmSync(frames, { recursive: true, force: true });
console.log(`wrote ${out}/tangible-parts.{mp4,png,-devpost.gif} (${n} frames)`);
