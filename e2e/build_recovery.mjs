// Build recovery against a live side engine: network loss, engine restart, page reload.
//   BARA_WEB=http://127.0.0.1:5190/  (a vite dev server proxied to the side engine)
//   BARA_ENGINE_RESTART=<shell command that kills and restarts that engine, blocking until up>
// node e2e/build_recovery.mjs. The browser is muted (it must never play speech out loud).
import { createRequire } from "node:module";
import { execSync } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const require = createRequire(resolve(here, "../web/package.json"));
const { chromium } = require("playwright");

const BASE = process.env.BARA_WEB ?? "http://127.0.0.1:5190/";
const RESTART = process.env.BARA_ENGINE_RESTART;
const rows = [];
const check = (name, ok, detail = "") => {
  rows.push({ name, ok: Boolean(ok), detail });
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? `  (${detail})` : ""}`);
};

async function api(path, init) {
  const res = await fetch(new URL(path, BASE), init);
  return res.json();
}

const browser = await chromium.launch({ headless: true, args: ["--mute-audio"] });
const ctx = await browser.newContext({ viewport: { width: 1500, height: 900 } });
const page = await ctx.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(String(e).slice(0, 200)));

const banner = () => page.locator(".conn-banner").first().textContent({ timeout: 500 }).catch(() => null);
const pill = () => page.locator(".topbar-build .status-pill").textContent({ timeout: 2000 }).catch(() => null);
const rowsOnScreen = () => page.locator(".part-row").count();
const waitFor = async (fn, ms, step = 250) => {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    const v = await fn();
    if (v) return v;
    await page.waitForTimeout(step);
  }
  return null;
};

const start = async () =>
  (
    await api("/v1/builds", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ prompt: "a small macropad with four keys and a knob" }),
    })
  ).build_id;
const open = async (buildId) => {
  // a reload mid-build: the address names the build, the stored tab list holds it
  const stored = JSON.stringify({ active: "c1", canvases: [{ id: "c1", name: null, build_id: buildId, prompt: "a macropad" }] });
  await page.evaluate((v) => localStorage.setItem("bara.canvases", v), stored).catch(() => {});
  await page.goto(new URL(`build/${buildId}`, BASE).href, { waitUntil: "domcontentloaded" });
  await page.evaluate((v) => localStorage.setItem("bara.canvases", v), stored);
  await page.reload({ waitUntil: "domcontentloaded" });
  return waitFor(async () => page.url().includes(buildId) && (await rowsOnScreen()) > 0, 60_000);
};
const serverParts = async (id) => (await api(`/v1/builds/${id}`)).build;

try {
  // 1. network loss in the browser while the engine keeps building
  const a = await start();
  check("build A started on the engine", !!a, a);
  check("reload mid-build shows the running build", await open(a));
  const before = await rowsOnScreen();
  await ctx.setOffline(true);
  const offBanner = await waitFor(async () => {
    const t = await banner();
    return t && /Reconnecting|Can't reach/.test(t) ? t : null;
  }, 5000);
  check("network loss shows the reconnecting banner within 5 s", !!offBanner, offBanner ?? "none");
  await page.waitForTimeout(10_000);
  const during = await rowsOnScreen();
  check("parts stay on screen while offline", during >= before, `${before} before, ${during} during`);
  const tOn = Date.now();
  await ctx.setOffline(false);
  const back = await waitFor(async () => (await banner()) === null, 20_000);
  check("reconnects once the network returns", !!back, `${Date.now() - tOn} ms`);
  await waitFor(async () => (await serverParts(a)).status !== "running", 120_000, 1000);
  await page.waitForTimeout(1500);
  const sa = await serverParts(a);
  const shownA = await rowsOnScreen();
  check(
    "after reconnect the screen caught up with the engine",
    shownA >= during && shownA > 0,
    `${during} offline -> ${shownA} rows; engine has ${sa.parts.length} parts, ${sa.status}`,
  );

  // 2. engine killed and restarted mid-build
  if (RESTART) {
    const b = await start();
    check("build B started on the engine", !!b, b);
    check("build B on screen", await open(b));
    const atKill = await rowsOnScreen();
    const statusAtKill = (await serverParts(b)).status;
    const t0 = Date.now();
    execSync(RESTART, { stdio: "inherit" });
    const restartMs = Date.now() - t0;
    const ended = await waitFor(async () => (await page.getByText(/engine restarted/).count()) > 0, 60_000, 500);
    check(
      "after an engine restart the build resumes and ends with a plain reason",
      !!ended || statusAtKill !== "running",
      `engine back in ${restartMs} ms, was ${statusAtKill} at kill, banner gone ${((await banner()) === null)}`,
    );
    const kept = await rowsOnScreen();
    check("parts built before the restart are still on screen", kept >= atKill, `${atKill} at kill, ${kept} after`);
    const sb = await serverParts(b);
    check("engine kept the build on disk", sb.status === "failed" || sb.status === "done", `${sb.status}, ${sb.parts.length} parts`);

    // 3. reload after the restart
    await page.reload({ waitUntil: "domcontentloaded" });
    const again = await waitFor(async () => page.url().includes(b) && (await rowsOnScreen()) >= kept, 30_000);
    check("reload brings the same build back", !!again, `${kept} rows before, ${await rowsOnScreen()} after`);
  }
  const mine = errors.filter((e) => !/__shot/.test(e));
  check("no page errors", mine.length === 0, mine.join(" | "));
} finally {
  await browser.close();
}
const failed = rows.filter((r) => !r.ok).length;
console.log(`${rows.length - failed}/${rows.length} passed`);
process.exit(failed ? 1 : 0);
