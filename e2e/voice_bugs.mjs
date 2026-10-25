// Voice agent check: the bugs voice agents usually ship with, each tried in a real Chromium with a
// fake microphone (a generated WAV) and the engine's speech endpoints stubbed, so it needs only the
// web dev server, not the engine. Mock mode, so no build is started by what it "says".
// Run: node e2e/voice_bugs.mjs        (BARA_WEB=http://localhost:5185/ to point elsewhere)
// Add --long to also run the 45 s "forgotten mic" check.
import { createRequire } from "node:module";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const require = createRequire(resolve(here, "../web/package.json"));
const playwright = require("playwright");

const BASE = (process.env.BARA_WEB ?? "http://localhost:5185/").replace(/\/?$/, "/") + "?mock=1";
const LONG = process.argv.includes("--long");
/** --browser=firefox|webkit runs the checks that don't need a recorded mic (Chromium alone can play a
 *  file as the microphone): speaking, keys, and turns driven by a stand-in recogniser. */
const ENGINE = (process.argv.find((a) => a.startsWith("--browser=")) ?? "--browser=chromium").split("=")[1];
const MP3 = readFileSync(resolve(here, "../voice-samples/cedar.mp3"));

const rows = [];
const check = (name, ok, detail = "") => {
  rows.push({ name, ok: Boolean(ok), detail });
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? `  (${detail})` : ""}`);
};

// ---------------------------------------------------------------- fake microphones

/** 16 kHz mono WAV: silence with one burst of voice-like noise, then a long tail (Chrome loops the file). */
function wav(dir, name, burstMs, { leadMs = 800, tailMs = 14000, amp = 0.35 } = {}) {
  const rate = 16000;
  const n = Math.round(((leadMs + burstMs + tailMs) / 1000) * rate);
  const buf = Buffer.alloc(44 + n * 2);
  buf.write("RIFF", 0);
  buf.writeUInt32LE(36 + n * 2, 4);
  buf.write("WAVEfmt ", 8);
  buf.writeUInt32LE(16, 16);
  buf.writeUInt16LE(1, 20);
  buf.writeUInt16LE(1, 22);
  buf.writeUInt32LE(rate, 24);
  buf.writeUInt32LE(rate * 2, 28);
  buf.writeUInt16LE(2, 32);
  buf.writeUInt16LE(16, 34);
  buf.write("data", 36);
  buf.writeUInt32LE(n * 2, 40);
  const a = Math.round((leadMs / 1000) * rate);
  const b = a + Math.round((burstMs / 1000) * rate);
  for (let i = 0; i < n; i++) {
    let v = 0;
    if (i >= a && i < b) {
      const t = i / rate;
      // a vowel-ish buzz with a syllable rhythm
      v = amp * (0.6 + 0.4 * Math.sin(2 * Math.PI * 4 * t)) * (Math.sin(2 * Math.PI * 180 * t) + 0.5 * Math.sin(2 * Math.PI * 360 * t) + 0.2 * (Math.random() - 0.5));
    }
    buf.writeInt16LE(Math.max(-32767, Math.min(32767, Math.round(v * 32767))), 44 + i * 2);
  }
  const file = join(dir, name);
  writeFileSync(file, buf);
  return file;
}

const dir = mkdtempSync(join(tmpdir(), "bara-voice-"));
const MICS = {
  speech: wav(dir, "speech.wav", 1400),
  cough: wav(dir, "cough.wav", 100),
  short: wav(dir, "short.wav", 450),
  silence: wav(dir, "silence.wav", 0, { amp: 0 }),
};

// ---------------------------------------------------------------- page harness

/**
 * A fresh page with: spoken words captured instead of building, getUserMedia counted and its
 * streams kept, the voice module on window.__v, and the engine's voice endpoints stubbed by `stt`
 * (a function of the request number) and `tts` ("ok" | "hang" | "fail-first").
 */
async function open(browser, { stt = () => ({ text: "" }), tts = "ok", fakeRecognition = false, passPrompts = false } = {}) {
  const ctx = await browser.newContext(ENGINE === "chromium" ? { permissions: ["microphone"] } : {});
  const page = await ctx.newPage();
  const net = { stt: 0, tts: [] };
  await page.route("**/v1/voice", (r) => r.fulfill({ json: { tts: true, stt: true, provider: "stub" } }));
  await page.route("**/v1/stt**", async (r) => {
    const n = ++net.stt;
    const out = stt(n);
    if (out === "hang") return; // never answers
    if (out.delay) await new Promise((res) => setTimeout(res, out.delay));
    await r.fulfill({ json: { text: out.text } }).catch(() => {});
  });
  await page.route("**/v1/tts**", async (r) => {
    const text = new URL(r.request().url()).searchParams.get("text");
    net.tts.push(text);
    if (tts === "hang") return;
    if (tts === "fail-first" && net.tts.length === 1) return r.fulfill({ status: 500, body: "no" });
    await r.fulfill({ status: 200, contentType: "audio/mpeg", body: MP3 });
  });
  await page.addInitScript(([fake, pass]) => {
    window.__sent = [];
    window.__asked = [];
    for (const ev of ["bara:prompt", "bara:ask"])
      window.addEventListener(ev, (e) => {
        window.__sent.push(e.detail);
        if (ev === "bara:ask") window.__asked.push(e.detail);
        if (!pass) e.stopImmediatePropagation();
      }, true);
    window.__streams = [];
    const gum = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
    navigator.mediaDevices.getUserMedia = async (c) => {
      const s = await gum(c);
      window.__streams.push(s);
      return s;
    };
    if (fake) {
      // a recogniser the test drives: window.__rec.say(text, final), and stop() settles 150 ms later
      // with whatever window.__finalWords holds, the way Chrome's last words arrive after stop()
      class FakeRec {
        constructor() {
          window.__rec = this;
        }
        start() {}
        say(text) {
          this.onresult?.({ results: [Object.assign([{ transcript: text }], { isFinal: false })] });
        }
        stop() {
          setTimeout(() => {
            if (window.__finalWords) this.say(window.__finalWords);
            this.onend?.();
          }, 150);
        }
        abort() {
          this.onend?.();
        }
      }
      window.SpeechRecognition = window.webkitSpeechRecognition = FakeRec;
    } else {
      // Chromium without Google's speech service: a recogniser that never hears anything, like
      // Chrome when that service is blocked. The recording has to carry every turn.
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
    }
  }, [fakeRecognition, passPrompts]);
  await page.goto(BASE);
  await page.waitForFunction(() => document.readyState === "complete");
  // The app's own copies of the modules: after a hot reload Vite serves them as voice.ts?t=…, and a
  // plain import would load second copies with their own state. Looked up again whenever missing,
  // since Vite may reload the page mid-run.
  const ensure = () =>
    page.evaluate(async () => {
      if (window.__v && window.__store) return;
      const mod = (path) =>
        import(
          /* @vite-ignore */ performance
            .getEntriesByType("resource")
            .map((e) => e.name)
            .find((n) => new URL(n).pathname === path) ?? path
        );
      window.__v = await mod("/src/voice/voice.ts");
      window.__store = await mod("/src/state/store.ts");
    });
  await ensure();
  const v = async (fn, arg) => {
    try {
      await ensure();
      return await page.evaluate(fn, arg);
    } catch (e) {
      if (!/context was destroyed|navigation|undefined \(reading '(useVoice|useApp)'\)/i.test(String(e))) throw e;
      await page.waitForLoadState("load");
      await ensure();
      return page.evaluate(fn, arg);
    }
  };
  const state = () => v(() => ({ ...window.__v.useVoice.getState() }));
  const until = async (fn, ms = 10000) => {
    const end = Date.now() + ms;
    while (Date.now() < end) {
      if (await v(fn)) return true;
      await page.waitForTimeout(100);
    }
    return false;
  };
  return { ctx, page, net, v, state, until };
}

async function withMic(mic, fn) {
  if (ENGINE !== "chromium" && mic !== MICS.silence) return;
  const browser =
    ENGINE === "firefox"
      ? await playwright.firefox.launch({ headless: true, firefoxUserPrefs: { "media.navigator.streams.fake": true, "media.navigator.permission.disabled": true, "media.autoplay.default": 0 } })
      : ENGINE === "webkit"
        ? await playwright.webkit.launch({ headless: true })
        : await playwright.chromium.launch({
            headless: true,
            args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", `--use-file-for-fake-audio-capture=${mic}`, "--autoplay-policy=no-user-gesture-required"],
          });
  try {
    await fn(browser);
  } finally {
    await browser.close();
  }
}

// ---------------------------------------------------------------- the checks

await withMic(MICS.speech, async (browser) => {
  {
    // the app's keys and this test must share one voice module, or nothing below means anything
    const p = await open(browser);
    await p.page.keyboard.down("Space");
    await p.page.waitForTimeout(150);
    check("test harness drives the app's own voice module", (await p.state()).listening);
    await p.page.keyboard.up("Space");
    await p.ctx.close();
  }
  {
    const p = await open(browser, { stt: () => ({ text: "um I I want a 12 mm knob" }) });
    const t0 = Date.now();
    await p.v(() => window.__v.startListening("auto"));
    const sent = await p.until(() => window.__sent.length > 0, 8000);
    const said = await p.v(() => window.__sent[0]);
    check("hands-free: a pause after speaking sends it, with no key or click", sent, `${((Date.now() - t0) / 1000).toFixed(1)} s`);
    check("ums and repeats dropped, millimetres kept", said === "I want a 12 mm knob", said);
    check("one turn sends exactly once", p.net.stt === 1 && (await p.v(() => window.__sent.length)) === 1, `${p.net.stt} STT calls`);
    await p.ctx.close();
  }
  {
    const p = await open(browser, { stt: () => ({ text: "a keyboard with a knob" }) });
    await p.page.keyboard.down("Space");
    await p.page.waitForTimeout(2600);
    // Cmd-Tab with Space held: the window blurs and the keyup never comes
    await p.v(() => window.dispatchEvent(new Event("blur")));
    const stopped = await p.until(() => !window.__v.useVoice.getState().listening, 1500);
    const sent = await p.until(() => window.__sent.length > 0, 6000);
    check("holding Space and switching windows doesn't leave the mic open", stopped);
    check("…and what was said before switching is still sent", sent);
    await p.page.keyboard.up("Space");
    await p.ctx.close();
  }
  {
    const p = await open(browser, { stt: () => ({ text: "first" }) });
    await p.v(() => window.__v.startListening("auto"));
    await p.until(() => window.__sent.length > 0, 8000);
    const live = await p.v(() => window.__streams.map((s) => s.getAudioTracks()[0].readyState));
    await p.v(() => window.__v.startListening("hold"));
    await p.page.waitForTimeout(300);
    const calls = await p.v(() => window.__streams.length);
    await p.v(() => window.__v.cancelListening());
    await p.v(() => window.__v.closeMic());
    const ended = await p.v(() => window.__streams.every((s) => s.getAudioTracks().every((t) => t.readyState === "ended")));
    check("next turn reuses the open mic (no reopen, no clipped first words)", calls === 1, `${calls} getUserMedia calls`);
    check("mic kept warm between turns, then really released", live[0] === "live" && ended);
    await p.ctx.close();
  }
  {
    // the first turn's words come back late, after a second turn has started
    const p = await open(browser, { stt: (n) => (n === 1 ? { text: "the first thing", delay: 2500 } : { text: "" }) });
    await p.v(() => window.__v.startListening("auto"));
    await p.until(() => window.__v.useVoice.getState().transcribing, 8000);
    await p.v(() => window.__v.startListening("hold"));
    await p.page.waitForTimeout(3000);
    const s = await p.state();
    const sent = await p.v(() => window.__sent);
    check("a late transcript doesn't overwrite the turn in progress", s.listening && s.heard !== "The first thing", JSON.stringify(s.heard));
    check("…but it is still sent", sent.includes("The first thing"), JSON.stringify(sent));
    await p.v(() => window.__v.cancelListening());
    await p.ctx.close();
  }
  {
    const p = await open(browser, { stt: () => "hang" });
    await p.v(() => window.__v.startListening("auto"));
    await p.until(() => window.__v.useVoice.getState().transcribing, 8000);
    const cleared = await p.until(() => !window.__v.useVoice.getState().transcribing, 17000);
    const s = await p.state();
    check("speech-to-text that never answers doesn't hang the UI", cleared && /too long/.test(s.error ?? ""), s.error ?? "");
    await p.ctx.close();
  }
  {
    // touch hold on the docked bot, taken over by a scroll: pointercancel, never pointerup
    const p = await open(browser, { stt: () => ({ text: "hello" }) });
    await p.page.click(".hero-cta");
    await p.page.waitForSelector(".agent-intro .ai-field input");
    await p.page.waitForTimeout(1200);
    await p.page.fill(".agent-intro .ai-field input", "a macropad");
    await p.page.keyboard.press("Enter");
    const docked = await p.page.waitForSelector(".promptbar.docked .bot-mic", { timeout: 15000 }).catch(() => null);
    if (docked) {
      await p.v(() => window.__v.stopSpeaking());
      await p.page.dispatchEvent(".promptbar.docked .bot-mic", "pointerdown", { pointerId: 1, pointerType: "touch" });
      await p.until(() => window.__v.useVoice.getState().listening, 2000);
      await p.page.dispatchEvent(".promptbar.docked .bot-mic", "pointercancel", { pointerId: 1, pointerType: "touch" });
      check("a cancelled touch on the bot doesn't leave the mic open", await p.until(() => !window.__v.useVoice.getState().listening, 2000));
      const key = await p.page.$(".talk-key kbd");
      check("project view shows the Space talk key", key && (await key.textContent()) === "Space");
    } else check("a cancelled touch on the bot doesn't leave the mic open", false, "project view never opened");
    await p.ctx.close();
  }
  if (LONG) {
    const p = await open(browser, { stt: () => ({ text: "long" }) });
    await p.page.keyboard.down("Space");
    const stopped = await p.until(() => !window.__v.useVoice.getState().listening, 48000);
    check("a forgotten hold ends by itself", stopped);
    await p.page.keyboard.up("Space");
    await p.ctx.close();
  }
});

await withMic(MICS.cough, async (browser) => {
  const p = await open(browser, { stt: () => ({ text: "Thank you." }) });
  await p.v(() => window.__v.startListening("auto"));
  await p.page.waitForTimeout(8500);
  check("a cough isn't sent to be written down", p.net.stt === 0 && (await p.v(() => window.__sent.length)) === 0, `${p.net.stt} STT calls`);
  check("…and the mic lets go when nothing more is said", !(await p.state()).listening);
  await p.ctx.close();
});

await withMic(MICS.short, async (browser) => {
  const p = await open(browser, { stt: () => ({ text: "Thank you." }) });
  await p.v(() => window.__v.startListening("auto"));
  await p.until(() => !window.__v.useVoice.getState().listening && !window.__v.useVoice.getState().transcribing, 9000);
  await p.page.waitForTimeout(300);
  const s = await p.state();
  check("a made-up 'Thank you.' from a bump is not sent as a request", (await p.v(() => window.__sent.length)) === 0 && /catch/.test(s.error ?? ""), s.error ?? "");
  await p.ctx.close();
});

await withMic(MICS.silence, async (browser) => {
  // Chromium only: Firefox's fake mic is a steady tone, never silent
  if (ENGINE === "chromium") {
    const p = await open(browser);
    await p.v(() => window.__v.startListening("auto"));
    await p.until(() => !!window.__v.useVoice.getState().error, 9000);
    check("a dead mic says so instead of failing quietly", /No sound/.test((await p.state()).error ?? ""));
    await p.ctx.close();
  }
  {
    const p = await open(browser, { tts: "hang" });
    await p.v(() => window.__v.setReplies(true));
    await p.v(() => window.__v.narrate("First line here."));
    await p.v(() => window.__v.narrate("Second line."));
    const moved = await p.until(() => window.__v.useVoice.getState().caption === "Second line.", 12000);
    check("a line whose audio never arrives doesn't silence everything after it", moved, JSON.stringify(p.net.tts));
    await p.v(() => window.__v.stopSpeaking());
    await p.ctx.close();
  }
  {
    const p = await open(browser, { tts: "fail-first" });
    await p.v(() => window.__v.setReplies(true));
    await p.v(() => {
      window.__said = [];
      const orig = speechSynthesis.speak.bind(speechSynthesis);
      speechSynthesis.speak = (u) => {
        window.__said.push(u.text);
        orig(u);
      };
    });
    await p.v(() => window.__v.speak("Alpha line one."));
    await p.until(() => window.__v.useVoice.getState().caption === null, 9000);
    await p.v(() => window.__v.speak("Beta line two."));
    await p.page.waitForTimeout(800);
    check("one failed audio request doesn't switch the session to the robotic voice", p.net.tts.includes("Beta line two."), JSON.stringify(p.net.tts));
    const fallback = await p.v(() => window.__said.filter((t) => t === "Alpha line one.").length);
    // (WebKit retries the audio request itself and may never need the fallback: 0 is fine, 2 is the bug)
    check("a failed line is never said twice by the fallback voice", fallback <= 1, `${fallback} times`);
    await p.v(() => window.__v.stopSpeaking());
    await p.ctx.close();
  }
  {
    const p = await open(browser);
    await p.v(() => window.__v.setReplies(true));
    await p.v(() => {
      window.__v.speak("Same words here.");
      window.__v.speak("Same words here.");
    });
    await p.page.waitForTimeout(1500);
    const n = p.net.tts.filter((t) => t === "Same words here.").length;
    check("the same line twice in a row plays once, not on top of itself", n === 1, `${n} plays`);
    await p.v(() => window.__v.stopSpeaking());
    await p.ctx.close();
  }
  {
    const p = await open(browser);
    await p.v(() => window.__v.setReplies(true));
    await p.v(() => window.__v.startListening("hold"));
    await p.page.waitForTimeout(200);
    await p.v(() => window.__v.speak("This would go into the mic.", true));
    await p.page.waitForTimeout(800);
    check("Bara never talks into an open mic", p.net.tts.length === 0 && (await p.state()).caption === null, JSON.stringify(p.net.tts));
    await p.v(() => window.__v.cancelListening());
    await p.ctx.close();
  }
  {
    const p = await open(browser);
    const before = (await p.state()).replies;
    await p.v(() => {
      const i = document.createElement("input");
      i.id = "probe";
      document.body.append(i);
    });
    await p.page.focus("#probe");
    await p.page.keyboard.type("v");
    const s = await p.state();
    check("typing V into an empty box types it, not toggling spoken replies", s.replies === before && (await p.page.inputValue("#probe")) === "v");
    await p.page.fill("#probe", "");
    await p.page.focus("#probe");
    await p.page.keyboard.down("Space");
    await p.page.waitForTimeout(150);
    check("Space in an empty box still talks", (await p.state()).listening);
    await p.page.keyboard.up("Space");
    await p.v(() => window.__v.cancelListening());
    await p.v(() => window.dispatchEvent(new KeyboardEvent("keydown", { code: "Space", key: " ", isComposing: true, bubbles: true })));
    await p.page.waitForTimeout(150);
    check("Space during IME composition is left to the input method", !(await p.state()).listening);
    await p.ctx.close();
  }
  {
    const p = await open(browser, { fakeRecognition: true });
    await p.v(() => window.__v.startListening("hold"));
    await p.v(() => window.__rec.say("build a keyboard"));
    await p.v(() => {
      window.__finalWords = "build a keyboard with an OLED";
      window.__v.stopListening();
    });
    await p.until(() => window.__sent.length > 0, 3000);
    const sent = await p.v(() => window.__sent[0]);
    check("the last words, which arrive just after letting go, are kept", sent === "Build a keyboard with an OLED", sent);
    await p.ctx.close();
  }
  {
    const p = await open(browser, { fakeRecognition: true });
    await p.v(() => window.__v.startListening("auto"));
    await p.v(() => window.__rec.say("make it blue"));
    await p.until(() => window.__sent.length > 0, 4000);
    await p.v(() => window.__v.listenForFollowUp());
    const hands = (await p.state()).listening;
    await p.v(() => window.__v.cancelListening());
    await p.v(() => {
      const i = document.createElement("input");
      i.id = "probe";
      document.body.append(i);
    });
    await p.page.focus("#probe");
    await p.page.keyboard.type("x");
    await p.v(() => window.__v.listenForFollowUp());
    check("a hands-free question gets the mic back after the answer", hands);
    check("…but not once you've started typing instead", !(await p.state()).listening);
    await p.ctx.close();
  }
  {
    const p = await open(browser, { fakeRecognition: true });
    await p.page.keyboard.down("Space");
    await p.page.keyboard.up("Space"); // a tap: hands-free
    await p.v(() => window.__rec.say("a keyboard with"));
    await p.page.waitForTimeout(1200);
    const waited = (await p.state()).listening;
    await p.page.keyboard.press("Space"); // Space again: send now
    await p.until(() => window.__sent.length > 0, 2000);
    check("a pause after a hanging word ('with') doesn't cut the speaker off", waited);
    check("Space while listening sends at once", (await p.v(() => window.__sent[0])) === "A keyboard with");
    await p.ctx.close();
  }
});

await withMic(MICS.silence, async (browser) => {
  // (Chromium only: it relies on the mic already being allowed, which only Chromium can grant here)
  if (ENGINE !== "chromium") return;
  // A whole spoken conversation on the mock build that asks questions ("make me a gadget"):
  // ask hands-free, hear Bara's question, answer it out loud, then ask about a part.
  const p = await open(browser, { fakeRecognition: true, passPrompts: true });
  const app = (fn) => p.v(fn);
  await app(() => window.__v.setReplies(true));
  await p.page.click(".hero-cta");
  await p.page.waitForSelector(".agent-intro .ai-field input");
  // the greeting is said, then Bara listens by itself (the mic is already allowed here)
  check("after 'What's up?' Bara listens without a click", await p.until(() => window.__v.useVoice.getState().listening, 9000));
  await app(() => window.__rec.say("um make me a gadget"));
  const started = await p.until(() => window.__store.useApp.getState().build?.status === "awaiting_input", 15000);
  check("spoken prompt starts the build", started);
  const asked = await p.until(() => window.__v.useVoice.getState().caption === "What should it do?", 5000);
  check("Bara's question is said at once, cutting in on progress chatter", asked, JSON.stringify(p.net.tts.slice(-3)));
  check("…and the mic opens for the answer", await p.until(() => window.__v.useVoice.getState().listening, 15000));
  await app(() => window.__rec.say("show the weather"));
  const answered = await p.until(
    () => window.__store.useApp.getState().log.some((e) => e.dir === "out" && e.type === "clarify.answer"),
    5000,
  );
  const outs = await app(() =>
    window.__store.useApp
      .getState()
      .log.filter((e) => e.dir === "out")
      .map((e) => {
        const option = JSON.parse(e.raw ?? "{}").payload?.option_id;
        return option ? `${e.type}:${option}` : e.type;
      }),
  );
  check("a spoken answer answers the question (picks the option)", answered && outs.includes("clarify.answer:o_weather"), outs.join(", "));
  check("…and doesn't restart the build", outs.filter((t) => t === "build.start").length === 1);
  // the second question ("How will it be powered?"), answered by place this time
  const second = await p.until(() => window.__v.useVoice.getState().caption === "How will it be powered?", 8000);
  check("the next question is said too", second);
  await p.until(() => window.__v.useVoice.getState().listening, 15000);
  await app(() => window.__rec.say("the first one"));
  await p.until(() => window.__store.useApp.getState().log.filter((e) => e.dir === "out" && e.type === "clarify.answer").length === 2, 5000);
  const done = await p.until(() => window.__store.useApp.getState().build?.status === "done", 30000);
  if (done) {
    await app(async () => {
      const path = "/src/three/Viewport3D.tsx";
      const url = performance.getEntriesByType("resource").map((e) => e.name).find((n) => new URL(n).pathname === path) ?? path;
      const { focusKeyOf } = await import(/* @vite-ignore */ url);
      const b = window.__store.useApp.getState().build;
      window.__store.focusPart(focusKeyOf(b, b.parts[0]));
    });
    await p.page.waitForTimeout(800);
    check("a part can be pulled into focus for the next check", await app(() => !!window.__store.useApp.getState().focusKey));
    await app(() => window.__v.stopSpeaking());
    await app(() => window.__v.startListening("auto"));
    await app(() => window.__rec.say("what does it connect to"));
    const asking = await p.until(() => window.__asked.at(-1) === "What does it connect to", 4000);
    check("with a part in focus, a spoken question goes to that part", asking, JSON.stringify(await app(() => window.__asked)));
    await app(() => window.__v.cancelListening());
  } else check("with a part in focus, a spoken question goes to that part", false, "build never finished");
  await p.ctx.close();
});

const failed = rows.filter((r) => !r.ok);
console.log(`\n${ENGINE}: ${rows.length - failed.length}/${rows.length} passed${LONG || ENGINE !== "chromium" ? "" : " (run with --long for the 45 s check)"}`);
process.exit(failed.length ? 1 : 0);
