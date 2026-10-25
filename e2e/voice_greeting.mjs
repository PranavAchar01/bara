// The landing hello, against a running engine with its own voice key: each click on Bara says a
// greeting through the engine's voice (/v1/tts, mood=greeting, played with Web Audio), never the
// browser's speechSynthesis, and the greeting changes from one click to the next.
//   BARA_WEB=http://localhost:5173/ node e2e/voice_greeting.mjs
import { createRequire } from "node:module";
import { existsSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const require = createRequire(resolve(here, "../web/package.json"));
const playwright = require("playwright");

const WEB = (process.env.BARA_WEB ?? "http://localhost:5173/").replace(/\/?$/, "/");
const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const SHOTS = resolve(here, "../.shots");
mkdirSync(SHOTS, { recursive: true });

const browser = await playwright.chromium.launch({
  ...(existsSync(CHROME) ? { executablePath: CHROME } : {}),
  headless: true,
  args: ["--mute-audio", "--autoplay-policy=no-user-gesture-required"],
});
let failed = 0;
const check = (name, ok, info = "") => {
  if (!ok) failed++;
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${info ? `  (${info})` : ""}`);
};

const heard = [];
for (let n = 0; n < 3; n++) {
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  await page.addInitScript(() => {
    window.__robot = 0;
    window.__pieces = 0;
    if (window.speechSynthesis) {
      const speak = speechSynthesis.speak.bind(speechSynthesis);
      speechSynthesis.speak = (u) => {
        window.__robot++;
        return speak(u);
      };
    }
    const start = AudioBufferSourceNode.prototype.start;
    AudioBufferSourceNode.prototype.start = function (...a) {
      window.__pieces++;
      return start.apply(this, a);
    };
  });
  const tts = [];
  page.on("response", (r) => {
    const u = new URL(r.url());
    if (u.pathname.endsWith("/v1/tts")) tts.push({ text: u.searchParams.get("text"), mood: u.searchParams.get("mood"), status: r.status(), type: r.headers()["content-type"] });
  });
  await page.goto(WEB);
  await page.click(".hero-cta");
  await page.waitForSelector(".agent-intro .ai-field input");
  await page.waitForFunction(() => window.__pieces > 0, null, { timeout: 8000 }).catch(() => {});
  await page.waitForTimeout(2500);
  const got = await page.evaluate(() => ({ robot: window.__robot, pieces: window.__pieces }));
  const t = tts[0];
  heard.push(t?.text);
  check(
    `click ${n + 1}: the hello is the engine's voice`,
    t && t.mood === "greeting" && t.status === 200 && /audio\/pcm/.test(t.type ?? "") && got.pieces > 0 && got.robot === 0,
    `${JSON.stringify(t?.text)} ${t?.type} pieces=${got.pieces} speechSynthesis=${got.robot}`,
  );
  if (n === 0) await page.screenshot({ path: resolve(SHOTS, "greeting.png") });
  await ctx.close();
}
check("the greeting changes between clicks", new Set(heard).size > 1, heard.join(" | "));
await browser.close();
process.exit(failed ? 1 : 0);
