// Voice latency, measured in a real Chrome against a running engine (real speech service, real
// keys held by the engine). Two numbers, each the median of several tries:
//   build line: a line from the build is handed to the voice -> its first sound
//   reply:      the speaker stops talking -> first sound of the answer (speech-to-text from a
//               recorded question, then the answer's speech; the answer itself is given at once,
//               so this is the voice's share of the wait, not the build's)
// and, for the reply, how soon Bara shows or sounds that it heard you.
// Run against a dev server whose /v1 proxy reaches an engine with voice (BARA_SERVER=http://127.0.0.1:PORT pnpm dev):
//   BARA_WEB=http://localhost:5173/ node e2e/voice_latency.mjs [MIC.wav]   (MIC: a 16 kHz WAV of a spoken question)
import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const require = createRequire(resolve(here, "../web/package.json"));
const playwright = require("playwright");

const WEB = (process.env.BARA_WEB ?? "http://localhost:5173/").replace(/\/?$/, "/");
const MIC = process.argv[2];
const TRIES = Number(process.env.TRIES ?? 5);
const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";

const LINES = [
  "Got the Seeed XIAO RP2040",
  "Routing the board now",
  "Found an open design to start from",
  "Got a 0.96 inch OLED",
  "Placing the switches",
  "Hmm. The 3.3 V rail can't feed that servo",
  "Done! 14 parts, all placed",
  "Got a rotary encoder",
];

const RUN = Math.floor(Math.random() * 90000) + 1000;
const median = (xs) => {
  const s = [...xs].filter((x) => x != null).sort((a, b) => a - b);
  return s.length ? Math.round(s[Math.floor(s.length / 2)]) : null;
};

const browser = await playwright.chromium.launch({
  executablePath: CHROME,
  headless: true,
  args: [
    "--mute-audio",
    "--autoplay-policy=no-user-gesture-required",
    "--use-fake-ui-for-media-stream",
    "--use-fake-device-for-media-stream",
    ...(MIC ? [`--use-file-for-fake-audio-capture=${MIC}`] : []),
  ],
});
const ctx = await browser.newContext({ permissions: ["microphone"] });
const page = await ctx.newPage();
await page.addInitScript(() => {
  // the first sound, whichever way the page plays it (an audio element, or Web Audio)
  window.__sounds = [];
  const mark = () => window.__sounds.push(performance.now());
  const play = HTMLMediaElement.prototype.play;
  HTMLMediaElement.prototype.play = function (...a) {
    this.addEventListener("playing", mark, { once: true });
    return play.apply(this, a);
  };
  const start = AudioBufferSourceNode.prototype.start;
  AudioBufferSourceNode.prototype.start = function (when = 0, ...a) {
    // when the sound is heard, not when it was queued
    const lead = Math.max(0, (when - this.context.currentTime) * 1000);
    if (!this.__cue) window.__sounds.push(performance.now() + lead);
    return start.call(this, when, ...a);
  };
  // a recogniser that hears nothing, so every turn goes through the engine's speech-to-text
  class DeafRec {
    start() {}
    stop() {
      setTimeout(() => this.onend?.(), 50);
    }
    abort() {
      this.onend?.();
    }
  }
  window.SpeechRecognition = window.webkitSpeechRecognition = DeafRec;
  window.__sent = [];
  window.__take = Math.floor(Math.random() * 90000);
  window.addEventListener(
    "bara:prompt",
    (e) => {
      window.__sent.push([performance.now(), e.detail]);
      e.stopImmediatePropagation();
      // the answer, straight away: what is measured is the voice, not the build
      window.__v.speak(`Sure. A split keyboard with an OLED, take ${++window.__take}.`, true);
    },
    true,
  );
});
await page.goto(`${WEB}?mock=1`);
await page.waitForFunction(() => document.readyState === "complete");
await page.evaluate(async () => {
  const mod = (path) =>
    import(/* @vite-ignore */ performance.getEntriesByType("resource").map((e) => e.name).find((n) => new URL(n).pathname === path) ?? path);
  window.__v = await mod("/src/voice/voice.ts");
});
await page.evaluate(() => window.__v.setReplies(true));
await page.waitForTimeout(1500);

const firstSoundAfter = async (t0, ms = 12000) => {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    const t = await page.evaluate((t0) => window.__sounds.find((x) => x >= t0), t0);
    if (t != null) return t - t0;
    await page.waitForTimeout(20);
  }
  return null;
};
const quiet = () => page.waitForFunction(() => window.__v.useVoice.getState().caption === null, null, { timeout: 20000 }).catch(() => {});

// build lines: new each time, then a line said before
const fresh = [];
for (let i = 0; i < TRIES; i++) {
  // a number no earlier run used, so no cache anywhere has this line yet
  const line = `${LINES[i % LINES.length]}, ${RUN + i} to go`;
  const t0 = await page.evaluate((l) => {
    const t = performance.now();
    window.__v.narrate(l);
    return t;
  }, line);
  fresh.push(await firstSoundAfter(t0));
  await quiet();
}
const repeat = [];
for (let i = 0; i < TRIES; i++) {
  const t0 = await page.evaluate(() => {
    const t = performance.now();
    window.__v.narrate("Done!");
    return t;
  });
  repeat.push(await firstSoundAfter(t0));
  await quiet();
}
console.log(`build line -> first sound (new line):  median ${median(fresh)} ms  ${JSON.stringify(fresh.map((x) => (x == null ? null : Math.round(x))))}`);
console.log(`build line -> first sound (said before): median ${median(repeat)} ms  ${JSON.stringify(repeat.map((x) => (x == null ? null : Math.round(x))))}`);

if (MIC) {
  const reply = [];
  const ack = [];
  const stt = [];
  for (let i = 0; i < TRIES; i++) {
    await page.evaluate(() => window.__v.startListening("hold"));
    // the mic file loops a question with a pause after it: let go once it has been said and the
    // room has gone quiet for half a second, the way someone lets go of Space
    await page.evaluate(
      () =>
        new Promise((done) => {
          const level = () => Number(getComputedStyle(document.documentElement).getPropertyValue("--mic-level") || 0);
          let loudFor = 0;
          let quietFor = 0;
          const tick = setInterval(() => {
            if (level() > 0.15) {
              loudFor += 50;
              quietFor = 0;
            } else if (loudFor > 1500) quietFor += 50;
            if (quietFor >= 500) {
              clearInterval(tick);
              done();
            }
          }, 50);
        }),
    );
    const t0 = await page.evaluate(() => {
      window.__ackAt = null;
      const off = window.__v.useVoice.subscribe((s) => {
        if (window.__ackAt == null && (s.thinking || s.transcribing)) window.__ackAt = performance.now();
      });
      window.__offAck = off;
      const t = performance.now();
      window.__v.stopListening();
      return t;
    });
    reply.push(await firstSoundAfter(t0, 15000));
    const r = await page.evaluate(() => ({ ack: window.__ackAt, sent: window.__sent.at(-1)?.[0], cue: window.__cueAt ?? null }));
    ack.push(r.ack != null ? r.ack - t0 : null);
    stt.push(r.sent != null ? r.sent - t0 : null);
    await page.evaluate(() => window.__offAck?.());
    await quiet();
    await page.waitForTimeout(400);
  }
  const said = await page.evaluate(() => window.__sent.at(-1)?.[1]);
  console.log(`reply: speech end -> words written down: median ${median(stt)} ms  ${JSON.stringify(stt.map((x) => (x == null ? null : Math.round(x))))}`);
  console.log(`reply: speech end -> first sound:        median ${median(reply)} ms  ${JSON.stringify(reply.map((x) => (x == null ? null : Math.round(x))))}`);
  console.log(`reply: speech end -> visible ack:        median ${median(ack)} ms`);
  console.log(`heard: ${JSON.stringify(said)}`);
}
await browser.close();
