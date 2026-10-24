// Mock-mode screenshots with an already installed browser (no downloads).
// Usage: node scripts/screens.mjs [baseUrl]   (dev server must be running)
import { chromium } from "playwright";
import { existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const outDir = join(here, "..", "screenshots");
const fixturesDir = join(here, "..", "..", "spec", "fixtures");
const base = process.argv[2] ?? "http://127.0.0.1:5173";
mkdirSync(outDir, { recursive: true });

function promptFor(name) {
  const f = JSON.parse(readFileSync(join(fixturesDir, `${name}.json`), "utf8"));
  return f.match_prompts?.[0] ?? name;
}

function findBrowser() {
  const cache = join(homedir(), "Library", "Caches", "ms-playwright");
  const dirs = existsSync(cache) ? readdirSync(cache) : [];
  const candidates = [];
  for (const d of dirs.filter((x) => x.startsWith("chromium-")).sort().reverse()) {
    candidates.push(join(cache, d, "chrome-mac-arm64", "Google Chrome for Testing.app", "Contents", "MacOS", "Google Chrome for Testing"));
    candidates.push(join(cache, d, "chrome-mac", "Chromium.app", "Contents", "MacOS", "Chromium"));
  }
  candidates.push("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome");
  return candidates.find((p) => existsSync(p)) ?? null;
}

const executablePath = findBrowser();
if (!executablePath) throw new Error("No installed Chromium or Chrome found; not downloading one.");
const browser = await chromium.launch({
  executablePath,
  headless: true,
  args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"],
});

const report = [];

async function run(name, url, steps) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
  const errors = [];
  const network = [];
  page.on("console", (m) => {
    if (m.type() === "error" || m.type() === "warning") errors.push(`${m.type()}: ${m.text()}`);
  });
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
  page.on("response", (r) => {
    if (r.status() >= 400) network.push(`${r.status()} ${new URL(r.url()).pathname}`);
  });
  page.on("requestfailed", (r) => network.push(`failed ${new URL(r.url()).pathname} ${r.failure()?.errorText ?? ""}`));
  let ok = true;
  let note = "";
  try {
    await page.goto(`${base}${url}`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector(".conn-pill.tone-ok", { timeout: 15000 });
    note = (await steps(page)) ?? "";
    await page.screenshot({ path: join(outDir, `${name}.png`) });
  } catch (e) {
    ok = false;
    note = String(e).split("\n")[0];
    await page.screenshot({ path: join(outDir, `${name}.png`) }).catch(() => {});
  }
  // A JS console line about a failed resource load is a network 404, not a code error.
  const jsErrors = errors.filter((e) => !/Failed to load resource|status of 40\d|status of 50\d/.test(e));
  report.push({ name, ok, note, jsErrors, network: [...new Set(network)] });
  await page.close();
}

async function prompt(page, text) {
  await page.fill(".prompt-input", text);
  await page.press(".prompt-input", "Enter");
}

async function waitDone(page) {
  await page.waitForSelector(".status-pill.st-done", { timeout: 30000 });
  await page.waitForTimeout(1500);
}

const q = (fx) => `/?mock=1&mock_speed=0.15&mock_fixture=${fx}`;

await run("01_home", "/?mock=1", async (page) => {
  await page.waitForSelector(".example-chip:not([disabled])");
});

await run("02_exact_keyboard_done", q("exact_keyboard"), async (page) => {
  await prompt(page, promptFor("exact_keyboard"));
  await waitDone(page);
  return `${await page.locator(".part-row").count()} part rows`;
});

await run("03_compose_wireless_split_oled_done", q("compose_wireless_split_oled"), async (page) => {
  await prompt(page, promptFor("compose_wireless_split_oled"));
  await waitDone(page);
  return `${await page.locator(".part-row").count()} part rows`;
});

await run("04_clarify_vague_gadget", q("clarify_vague_gadget"), async (page) => {
  await prompt(page, promptFor("clarify_vague_gadget"));
  await page.waitForSelector(".clarify.asking", { timeout: 20000 });
  await page.waitForTimeout(400);
});

await run("05_failed_critical_missing", q("failed_critical_missing"), async (page) => {
  await prompt(page, promptFor("failed_critical_missing"));
  await page.waitForSelector(".failure", { timeout: 20000 });
  await page.waitForTimeout(600);
});

await run("06_edit_swap_applied", q("exact_keyboard"), async (page) => {
  await prompt(page, promptFor("exact_keyboard"));
  await waitDone(page);
  const row = page.locator(".part-group", { hasText: /switch/i }).locator(".part-row").first();
  await row.click();
  await page.click(".insp-actions >> text=Swap");
  await page.waitForSelector(".alt-btn:not([disabled])", { timeout: 10000 });
  await page.locator(".alt-btn:not([disabled])").first().click();
  await page.waitForSelector(".edit-status.ph-applied", { timeout: 20000 });
  await page.waitForTimeout(800);
  return (await page.locator(".edit-status").innerText()).replace(/\s+/g, " ");
});

await browser.close();
writeFileSync(join(outDir, "report.json"), JSON.stringify(report, null, 2));
for (const r of report) {
  process.stdout.write(
    `${r.ok ? "ok  " : "FAIL"} ${r.name} ${r.note}\n     js errors: ${r.jsErrors.length ? r.jsErrors.join(" | ") : "none"}\n     network >=400: ${r.network.length ? r.network.slice(0, 6).join(", ") + (r.network.length > 6 ? ` (+${r.network.length - 6})` : "") : "none"}\n`,
  );
}
