// Bara's voice (Figma 19 Voice · talk to Bara). Hold Space to talk and let go to send, or tap Space (or
// the mic) and just talk: a pause at the end of what you said sends it. Ums and stutters are taken out
// before Bara sees it. Bara answers out loud through the engine's streamed speech (OpenAI when the
// engine has its key), with the words shown under the eyes; without it, the browser's own speech fills
// in, so nothing depends on one service. Replies are cut to one or two short sentences, the first one
// starts playing while the next downloads, talking again stops it (barge-in), and the time from the
// end of your speech to the first sound is kept in `latencyMs`.
import { create } from "zustand";
import { speechFor } from "../bot/mood";
import { answerClarify } from "../net/client";
import { authHeaders, serverUrl } from "../net/mode";
import { showToast, useApp } from "../state/store";
import { cleanTranscript, endOfTurnMs, isNoise, pickOption } from "./turn";

/** hold: Space (or the bot) is held and letting go sends. auto: a pause at the end sends. */
export type ListenMode = "hold" | "auto";

export interface VoiceState {
  /** The mic is open. */
  listening: boolean;
  mode: ListenMode | null;
  /** Words heard so far while listening (live captions where the browser can). */
  heard: string;
  /** Sending the recording to be written down. */
  transcribing: boolean;
  /** What Bara is saying right now, shown as a caption. */
  caption: string | null;
  /** Replies are spoken. Turns on the first time you talk; V toggles it. */
  replies: boolean;
  error: string | null;
  /** Milliseconds from the end of your speech to the first sound of the answer, last time. */
  latencyMs: number | null;
}

const STORE_KEY = "voice.replies";
function storedReplies(): boolean {
  try {
    return localStorage.getItem(STORE_KEY) === "1";
  } catch {
    return false;
  }
}

export const useVoice = create<VoiceState>(() => ({
  listening: false,
  mode: null,
  heard: "",
  transcribing: false,
  caption: null,
  replies: storedReplies(),
  error: null,
  latencyMs: null,
}));

// when you stopped talking, for the latency reading; cleared once the first sound plays
let speechEndedAt: number | null = null;
function markSpeechEnd(): void {
  speechEndedAt = performance.now();
}
function markFirstSound(): void {
  if (speechEndedAt === null) return;
  const ms = Math.round(performance.now() - speechEndedAt);
  speechEndedAt = null;
  // an answer long after you stopped talking is some other line, not the reply to that speech
  if (ms < 30000) useVoice.setState({ latencyMs: ms });
}

export function setReplies(on: boolean, announce = false): void {
  useVoice.setState({ replies: on });
  if (announce) showToast(on ? "Bara will answer out loud. Press V to turn it off." : "Bara will answer in text only. Press V to hear it.");
  try {
    localStorage.setItem(STORE_KEY, on ? "1" : "0");
  } catch {
    // storage blocked: the choice lasts for this page
  }
  if (!on) stopSpeaking();
}

// ---------------------------------------------------------------- speaking

let audio: HTMLAudioElement | null = null;
/** The next sentence, already downloading while the current one plays. */
let upNext: HTMLAudioElement | null = null;
let engineVoice: boolean | null = null;
/** Engine lines that failed in a row: one network blip shouldn't hand the rest of the session to
 *  the browser's voice, three in a row should. */
let engineFails = 0;
/** One number per thing said, so a late callback from something already stopped does nothing (two
 *  identical lines in a row must not both play). */
let speechGen = 0;
/** If a line never reports its end (a stalled stream, Chrome's speech that just stops), let it go,
 *  or every line after it would wait forever. */
let stuckTimer = 0;
/** Chrome drops an utterance's end event if nothing holds on to the utterance. */
let utterance: SpeechSynthesisUtterance | null = null;

/** Sentences to speak one by one: the first starts sooner than the whole reply would, and the
 *  rest are fetched while it plays. Very short pieces ride with the next so it doesn't sound clipped. */
export function sentences(text: string): string[] {
  const out: string[] = [];
  let carry = "";
  for (const piece of text.split(/(?<=[.!?])\s+/)) {
    carry = carry ? `${carry} ${piece}` : piece;
    if (carry.length >= 16) {
      out.push(carry);
      carry = "";
    }
  }
  if (carry) {
    if (out.length && carry.length < 16) out[out.length - 1] += ` ${carry}`;
    else out.push(carry);
  }
  return out;
}

/** A spoken reply is one or two short sentences: more is a lecture, and it delays the first word of
 *  the next turn. The caption shows exactly what is said. */
export function trimReply(text: string, askedWords = 12): string {
  const pieces = text.trim().replace(/\s+/g, " ").split(/(?<=[.!?])\s+/).filter(Boolean);
  // a short ask gets one short sentence; a longer one can have two
  const said = pieces.slice(0, askedWords <= 5 ? 1 : 2).join(" ");
  if (said.length <= 200) return said;
  if (pieces[0].length <= 200) return pieces[0];
  return `${said.slice(0, 197).replace(/\s+\S*$/, "")}...`;
}

function ttsAudio(line: string): HTMLAudioElement {
  const a = new Audio(serverUrl(`/v1/tts?text=${encodeURIComponent(line)}`));
  a.preload = "auto";
  a.addEventListener("playing", markFirstSound, { once: true });
  return a;
}

async function engineCanSpeak(): Promise<boolean> {
  if (engineVoice !== null) return engineVoice;
  try {
    const res = await fetch(serverUrl("/v1/voice"), { headers: authHeaders() });
    engineVoice = res.ok && Boolean(((await res.json()) as { tts?: boolean }).tts);
  } catch {
    engineVoice = false;
  }
  return engineVoice;
}

export function stopSpeaking(): void {
  speechGen++;
  window.clearTimeout(stuckTimer);
  if (utterance) utterance.onend = null;
  utterance = null;
  for (const a of [audio, upNext]) {
    if (!a) continue;
    a.pause();
    a.src = "";
  }
  audio = null;
  upNext = null;
  afterSpeech = null;
  waiting = null;
  if (typeof speechSynthesis !== "undefined") speechSynthesis.cancel();
  useVoice.setState({ caption: null });
}

/** The most natural voice the browser has, for when the engine can't speak. */
function browserVoice(): SpeechSynthesisVoice | null {
  const voices = speechSynthesis.getVoices().filter((v) => v.lang.startsWith("en"));
  const rank = (v: SpeechSynthesisVoice) =>
    (/premium|enhanced|natural|neural/i.test(v.name) ? 4 : 0) + (/google/i.test(v.name) ? 2 : 0) + (/samantha|ava|allison|aria|jenny/i.test(v.name) ? 1 : 0);
  return voices.sort((a, b) => rank(b) - rank(a))[0] ?? null;
}

/** Runs once a reply has been said all the way through (not when it is cut off). */
let afterSpeech: (() => void) | null = null;

function finished(): void {
  speechGen++;
  window.clearTimeout(stuckTimer);
  useVoice.setState({ caption: null });
  const then = afterSpeech;
  const next = waiting;
  afterSpeech = null;
  waiting = null;
  then?.();
  if (next && !useVoice.getState().listening) speak(next.text, false, next.then);
}

/** A line that came in while another was being said: it waits its turn instead of cutting in. */
let waiting: { text: string; then?: () => void } | null = null;

/** Says a line from the build. If Bara is mid-sentence the line waits, and only the newest waiting
 *  line is kept, so the voice never falls behind the build or talks over itself. */
export function narrate(text: string, then?: () => void): void {
  const s = useVoice.getState();
  if (!s.replies || s.listening || !text.trim()) return;
  if (s.caption) waiting = { text, then };
  else speak(text, false, then);
}

/** Lines of a build said out loud: the same lines the bot shows, one now and then, never one per
 *  event. A question from Bara is always said, and hands the mic back if you were talking hands-free. */
const SPEECH_GAP_MS = 2500;
const ALWAYS_SAY = new Set(["build.done", "build.failed", "clarify.request"]);

export function bindBuildVoice(): () => void {
  let seen = useApp.getState().log.at(-1)?.id ?? 0;
  let lastSaid = 0;
  return useApp.subscribe((s) => {
    const last = s.log.at(-1)?.id ?? seen;
    if (last === seen) return;
    // only the canvas on screen; a replay re-performs a build, it doesn't need narrating
    const fresh = s.replaying ? [] : s.log.filter((e) => e.id > seen && e.dir === "in" && (!e.buildId || e.buildId === s.build?.build_id));
    seen = last;
    for (const e of fresh) {
      const line = speechFor(e);
      const now = performance.now();
      if (!line || (!ALWAYS_SAY.has(e.type) && now - lastSaid < SPEECH_GAP_MS)) continue;
      lastSaid = now;
      narrate(line, e.type === "clarify.request" ? listenForFollowUp : undefined);
    }
  });
}

function speakInBrowser(text: string, gen: number): void {
  if (typeof speechSynthesis === "undefined") {
    finished();
    return;
  }
  const u = new SpeechSynthesisUtterance(text);
  utterance = u;
  const v = browserVoice();
  if (v) u.voice = v;
  u.rate = 1.1;
  u.onstart = markFirstSound;
  u.onend = () => gen === speechGen && finished();
  // blocked (no click on the page yet) or failed: move on, so the next line isn't stuck behind it
  u.onerror = () => gen === speechGen && finished();
  speechSynthesis.speak(u);
}

/** Says a reply when replies are on (or `force`); the caption shows while it plays. `then` runs
 *  when it has been said through, which is how a spoken conversation hands the turn back. */
export function speak(text: string, force = false, then?: () => void): void {
  const clean = trimReply(text, askedWords);
  if (!clean || (!force && !useVoice.getState().replies)) return;
  // the mic is open: talking now would talk over the person and into the mic
  if (useVoice.getState().listening) return;
  stopSpeaking();
  const gen = speechGen;
  afterSpeech = then ?? null;
  useVoice.setState({ caption: clean });
  // generous: about 13 characters a second, plus time for the first audio to arrive
  stuckTimer = window.setTimeout(() => {
    if (gen !== speechGen) return;
    for (const a of [audio, upNext]) a?.pause();
    if (typeof speechSynthesis !== "undefined") speechSynthesis.cancel();
    finished();
  }, 6000 + clean.length * 75);
  void engineCanSpeak().then((ok) => {
    if (gen !== speechGen) return;
    if (!ok) {
      speakInBrowser(clean, gen);
      return;
    }
    // GET, so the audio element plays the stream as it arrives instead of waiting for the file
    const lines = sentences(clean);
    const play = (i: number, a: HTMLAudioElement) => {
      audio = a;
      upNext = i + 1 < lines.length ? ttsAudio(lines[i + 1]) : null;
      a.onended = () => {
        if (audio !== a || gen !== speechGen) return;
        engineFails = 0;
        if (upNext) play(i + 1, upNext);
        else finished();
      };
      a.onerror = () => {
        if (audio !== a || gen !== speechGen) return;
        if (++engineFails >= 3) engineVoice = false;
        speakInBrowser(lines.slice(i).join(" "), gen);
      };
      void a.play().catch(() => {
        if (audio === a && gen === speechGen) speakInBrowser(lines.slice(i).join(" "), gen);
      });
    };
    play(0, ttsAudio(lines[0]));
  });
}

// ask the engine once, early, so the first reply doesn't wait on it
if (typeof window !== "undefined") void engineCanSpeak();

// ---------------------------------------------------------------- listening

type RecognitionResult = ArrayLike<{ transcript: string }> & { isFinal: boolean };
type Recognition = {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  start: () => void;
  stop: () => void;
  abort: () => void;
  onresult: ((e: { results: ArrayLike<RecognitionResult> }) => void) | null;
  onend: (() => void) | null;
  onerror: ((e: { error: string }) => void) | null;
};

/** A Space press shorter than this is a tap: listen hands-free instead of while held. */
const TAP_MS = 260;
/** Hands-free with nothing said for this long: let it go quietly. */
const QUIET_MS = 7000;
/** After the turn ends, how long to wait for the recogniser's last words before sending what it has. */
const FINAL_WAIT_MS = 300;
/** With no words from the recogniser, a silence this long after speech ends a hands-free turn. */
const VAD_SILENCE_MS = 900;
/** Below this the mic is giving nothing at all: muted, or the wrong input picked. */
const DEAD_MIC_RMS = 0.002;
/** Less speech than this is a cough or a bump, not words: not worth sending to be written down
 *  (speech-to-text models tend to invent a "Thank you." for near-silence). */
const MIN_SPEECH_MS = 250;
/** A turn this long ends by itself (a stuck key, a forgotten mic), well under the 8 MB upload cap. */
const MAX_TURN_MS = 45_000;
const STT_TIMEOUT_MS = 15_000;
/** The mic stays open this long after a turn, so the next turn starts recording at once instead of
 *  clipping its first words while the browser reopens the mic. */
const WARM_MS = 20_000;

/** One turn of listening. The browser's recogniser gives live words where it works; the mic is
 *  recorded alongside, so when the recogniser hears nothing (it can fail without a word, offline or
 *  blocked) the engine still writes it down. The mic level decides when someone actually spoke. */
interface Turn {
  id: number;
  recognition: Recognition | null;
  recorder: MediaRecorder | null;
  chunks: Blob[];
  started: number;
  /** The mic level says someone talked, and when it was last loud. */
  spoke: boolean;
  lastLoud: number;
  loudest: number;
  /** How long the mic was loud in all, to tell words from a cough. */
  loudMs: number;
  /** The level watcher is running (the mic opened). */
  metered: boolean;
  unwatch: () => void;
  /** Ended: no more listening. Words may still come in until it is sent (see finish). */
  done: boolean;
  sent: boolean;
  maxTimer: number;
}

let cur: Turn | null = null;
/** The turn whose recording is being written down (only it may clear the spinner). */
let sttFor = 0;
/** The open mic kept warm between turns (WARM_MS). */
let warm: { stream: MediaStream; timer: number } | null = null;
let turns = 0;
let delivered = 0;
let endTimer = 0;
let quietTimer = 0;
let quietMs = QUIET_MS;
/** When the last spoken turn was sent hands-free; replies to it hand the mic straight back. */
let lastHandsFree = 0;

function recognitionClass(): (new () => Recognition) | null {
  const w = window as unknown as { SpeechRecognition?: new () => Recognition; webkitSpeechRecognition?: new () => Recognition };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

function setLevel(v: number): void {
  document.documentElement.style.setProperty("--mic-level", v.toFixed(2));
}

/** Where a finished utterance goes: the part in focus if there is one, otherwise the prompt. */
// how long the last thing said to Bara was, so the reply can match it
let askedWords = 12;
function deliver(text: string, id: number, handsFree: boolean): void {
  if (delivered === id) return;
  delivered = id;
  const t = cleanTranscript(text);
  if (!t) return;
  lastHandsFree = handsFree ? performance.now() : 0;
  askedWords = t.split(/\s+/).length;
  if (!useVoice.getState().replies) setReplies(true);
  // Bara asked something: the reply answers it, it doesn't start a new build
  const q = useApp.getState().build?.clarify;
  if (q && useApp.getState().build?.status === "awaiting_input") {
    const option = pickOption(t, q.options);
    if (option) answerClarify({ option_id: option });
    else if (q.allow_free_text) answerClarify({ free_text: t });
    else window.dispatchEvent(new CustomEvent("bara:prompt", { detail: t }));
    return;
  }
  const target = useApp.getState().focusKey ? "bara:ask" : "bara:prompt";
  window.dispatchEvent(new CustomEvent(target, { detail: t }));
}

async function transcribe(blob: Blob, t: Turn, handsFree: boolean): Promise<void> {
  // a newer turn has the screen; this one's words, errors and spinner must not land on it
  const stale = () => turns !== t.id;
  sttFor = t.id;
  useVoice.setState({ transcribing: true });
  const abort = new AbortController();
  const timer = window.setTimeout(() => abort.abort(), STT_TIMEOUT_MS);
  try {
    const build = useApp.getState().build?.build_id;
    const res = await fetch(serverUrl(`/v1/stt${build ? `?build_id=${encodeURIComponent(build)}` : ""}`), {
      method: "POST",
      headers: { ...authHeaders(), "content-type": blob.type || "audio/webm" },
      body: blob,
      signal: abort.signal,
    });
    if (!res.ok) throw new Error(`Couldn't write that down (${res.status}).`);
    const text = ((await res.json()) as { text?: string }).text ?? "";
    const words = isNoise(text, t.loudMs) ? "" : cleanTranscript(text);
    // still the person's words, but a newer turn owns the field, so leave what it shows alone
    if (!stale()) useVoice.setState({ heard: words, ...(words ? {} : { error: "Didn't catch that. Try again?" }) });
    if (words) deliver(words, t.id, handsFree);
  } catch (e) {
    if (stale()) return;
    const timedOut = e instanceof DOMException && e.name === "AbortError";
    useVoice.setState({ error: timedOut ? "Writing that down took too long. Try again?" : e instanceof Error ? e.message : "Couldn't hear that." });
  } finally {
    window.clearTimeout(timer);
    if (sttFor === t.id) useVoice.setState({ transcribing: false });
  }
}

/** Hands-free: decide whether the speaker has finished. Words, when there are any, set the pause
 *  (endOfTurnMs); without words the mic level alone does. */
function armEndOfTurn(t: Turn): void {
  const s = useVoice.getState();
  if (t.done || s.mode !== "auto") return;
  window.clearTimeout(endTimer);
  const wait = endOfTurnMs(s.heard);
  if (wait === null) return;
  const fire = () => {
    // still talking, the words just haven't caught up
    if (t.metered && performance.now() - t.lastLoud < 250) endTimer = window.setTimeout(fire, 250);
    else void finish(t, true);
  };
  endTimer = window.setTimeout(fire, wait);
}

function armQuiet(t: Turn): void {
  window.clearTimeout(quietTimer);
  if (useVoice.getState().mode !== "auto") return;
  quietTimer = window.setTimeout(() => {
    if (t.done || t.spoke || useVoice.getState().heard) return;
    void finish(t, false);
    if (t.metered && t.loudest < DEAD_MIC_RMS) useVoice.setState({ error: "No sound from your mic. Check which input is selected." });
  }, quietMs);
}

/** Watches the mic level: drives the level ring (--mic-level) and tells speech from silence. */
function watchLevel(stream: MediaStream, t: Turn): () => void {
  const Ctx = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!Ctx) return () => {};
  const ctx = new Ctx();
  const analyser = ctx.createAnalyser();
  analyser.fftSize = 1024;
  ctx.createMediaStreamSource(stream).connect(analyser);
  const buf = new Float32Array(analyser.fftSize);
  let floor = 0.005;
  t.metered = true;
  const tick = window.setInterval(() => {
    if (t.done) return;
    analyser.getFloatTimeDomainData(buf);
    let sum = 0;
    for (const v of buf) sum += v * v;
    const rms = Math.sqrt(sum / buf.length);
    const now = performance.now();
    t.loudest = Math.max(t.loudest, rms);
    // the first moment is room noise; after that the floor only drifts down
    if (now - t.started < 250) floor = Math.max(floor, rms);
    else if (rms < floor) floor = floor * 0.95 + rms * 0.05;
    const loud = rms > Math.max(0.015, floor * 2.5);
    if (loud) {
      t.spoke = true;
      t.lastLoud = now;
      t.loudMs += 50;
    }
    setLevel(Math.min(1, rms * 12));
    // hands-free with no words from the recogniser: the level alone ends the turn
    if (useVoice.getState().mode === "auto" && !useVoice.getState().heard && t.spoke && now - t.lastLoud > VAD_SILENCE_MS) void finish(t, true);
  }, 50);
  return () => {
    window.clearInterval(tick);
    setLevel(0);
    void ctx.close();
  };
}

function liveStream(): MediaStream | null {
  if (!warm) return null;
  window.clearTimeout(warm.timer);
  const s = warm.stream;
  warm = null;
  return s.getAudioTracks().some((x) => x.readyState === "live") ? s : null;
}

/** Done with the mic for now: keep it open a little in case another turn follows, then let it go. */
function releaseMic(stream: MediaStream): void {
  if (warm && warm.stream !== stream) {
    window.clearTimeout(warm.timer);
    warm.stream.getTracks().forEach((x) => x.stop());
  }
  warm = { stream, timer: window.setTimeout(closeMic, WARM_MS) };
}

/** Lets go of the mic now (leaving the page, or the warm time ran out). */
export function closeMic(): void {
  if (!warm) return;
  window.clearTimeout(warm.timer);
  warm.stream.getTracks().forEach((x) => x.stop());
  warm = null;
}

async function openMic(t: Turn): Promise<void> {
  let stream: MediaStream | null = null;
  try {
    stream = liveStream() ?? (await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } }));
    if (t.done) {
      releaseMic(stream);
      return;
    }
    const rec = new MediaRecorder(stream);
    rec.ondataavailable = (e) => {
      if (e.data.size) t.chunks.push(e.data);
    };
    const unwatch = watchLevel(stream, t);
    const s = stream;
    t.unwatch = () => {
      unwatch();
      releaseMic(s);
    };
    t.recorder = rec;
    rec.start();
  } catch {
    // never leave the mic on when recording couldn't start
    stream?.getTracks().forEach((x) => x.stop());
    // no recording; the recogniser may still hear, and if there is none either, say so
    if (!t.recognition && !t.done) {
      useVoice.setState({ error: "Microphone access is blocked." });
      void finish(t, false);
    }
  }
}

/** The recording so far, once the recorder has handed over its last piece. */
function stopRecording(t: Turn): Promise<Blob | null> {
  const rec = t.recorder;
  t.recorder = null;
  if (!rec || rec.state === "inactive") {
    t.unwatch();
    return Promise.resolve(null);
  }
  return new Promise((resolve) => {
    rec.onstop = () => {
      t.unwatch();
      resolve(t.chunks.length ? new Blob(t.chunks, { type: rec.mimeType || "audio/webm" }) : null);
    };
    rec.stop();
  });
}

/** Ends a turn. Sending: the recogniser's words if it has any (fastest), else the recording, written
 *  down by the engine, if the mic heard someone. */
async function finish(t: Turn, send: boolean): Promise<void> {
  if (t.done) return;
  t.done = true;
  window.clearTimeout(endTimer);
  window.clearTimeout(quietTimer);
  window.clearTimeout(t.maxTimer);
  if (cur === t) cur = null;
  if (send) markSpeechEnd();
  const handsFree = useVoice.getState().mode === "auto";
  useVoice.setState({ listening: false, mode: null, ...(send ? {} : { heard: "" }) });
  const r = t.recognition;
  t.recognition = null;
  const recording = stopRecording(t);
  if (!send) {
    t.sent = true;
    r?.abort();
    void recording;
    return;
  }
  if (r) {
    if (useVoice.getState().heard) {
      // let the recogniser settle its last words, but never make the speaker wait long on it
      await new Promise<void>((resolve) => {
        r.onend = () => resolve();
        window.setTimeout(resolve, FINAL_WAIT_MS);
        r.stop();
      });
    }
    r.abort();
  }
  t.sent = true;
  const heard = useVoice.getState().heard;
  const blob = await recording;
  if (heard) deliver(heard, t.id, handsFree);
  else if (t.loudMs >= MIN_SPEECH_MS && blob) await transcribe(blob, t, handsFree);
  else if (t.metered && t.loudest < DEAD_MIC_RMS) useVoice.setState({ error: "No sound from your mic. Check which input is selected." });
}

/** Opens the mic. Hands-free ("auto") sends when the speaker pauses; "hold" sends when let go. */
export async function startListening(mode: ListenMode = "auto", opts: { quietMs?: number } = {}): Promise<void> {
  if (useVoice.getState().listening) return;
  // barge-in: talking while Bara talks stops it at once, before the mic even opens
  stopSpeaking();
  speechEndedAt = null;
  quietMs = opts.quietMs ?? QUIET_MS;
  const t: Turn = {
    id: ++turns,
    recognition: null,
    recorder: null,
    chunks: [],
    started: performance.now(),
    spoke: false,
    lastLoud: 0,
    loudest: 0,
    loudMs: 0,
    metered: false,
    unwatch: () => {},
    done: false,
    sent: false,
    maxTimer: 0,
  };
  cur = t;
  t.maxTimer = window.setTimeout(() => void finish(t, true), MAX_TURN_MS);
  useVoice.setState({ listening: true, mode, heard: "", error: null });
  armQuiet(t);
  const Rec = recognitionClass();
  if (Rec) {
    const r = new Rec();
    r.continuous = true;
    r.interimResults = true;
    r.lang = navigator.language || "en-US";
    r.onresult = (e) => {
      // the last words can arrive just after the turn ended (finish waits for them); after it's sent, none
      if (t.sent) return;
      let text = "";
      for (let i = 0; i < e.results.length; i++) text += e.results[i][0].transcript;
      useVoice.setState({ heard: cleanTranscript(text) });
      armEndOfTurn(t);
    };
    r.onerror = (e) => {
      if (t.recognition !== r) return;
      t.recognition = null;
      if (e.error === "not-allowed" || e.error === "audio-capture") {
        useVoice.setState({ error: e.error === "not-allowed" ? "Microphone access is blocked." : "No microphone found." });
        void finish(t, false);
      }
      // anything else (network, no service, no speech): the recording carries on without it
    };
    r.onend = () => {
      if (t.recognition !== r) return;
      t.recognition = null;
      // the recogniser gave up on its own; hands-free with words in hand, that is the end of the turn
      if (useVoice.getState().mode === "auto" && useVoice.getState().heard) void finish(t, true);
    };
    try {
      r.start();
      t.recognition = r;
    } catch {
      // no recogniser after all; the recording is enough
    }
  }
  await openMic(t);
}

/** A held press turned out to be a tap: keep listening, hands-free. */
export function keepListening(): void {
  const t = cur;
  if (!t || !useVoice.getState().listening) return;
  useVoice.setState({ mode: "auto" });
  armQuiet(t);
  armEndOfTurn(t);
}

/** Stop and send what was said. */
export function stopListening(): void {
  if (cur) void finish(cur, true);
  else useVoice.setState({ listening: false, mode: null });
}

/** Stop and throw it away (Esc). */
export function cancelListening(): void {
  if (cur) void finish(cur, false);
  useVoice.setState({ listening: false, mode: null, heard: "" });
}

/** For a reply's `then`: if the question was asked hands-free, listen for the next one. */
export function listenForFollowUp(): void {
  if (!lastHandsFree || performance.now() - lastHandsFree > 60_000 || useVoice.getState().listening) return;
  void startListening("auto", { quietMs: 5000 });
}

/** The mic is already allowed, so opening it won't put a permission prompt in front of anyone. */
export async function micAllowed(): Promise<boolean> {
  try {
    return (await navigator.permissions.query({ name: "microphone" as PermissionName })).state === "granted";
  } catch {
    return false;
  }
}

/** Space belongs to the page here: a text field with something in it, or a control reached by
 *  keyboard (Space presses it). An empty field gives Space to the voice, since a leading space types nothing. */
function typing(t: EventTarget | null, space: boolean): boolean {
  const el = t as HTMLElement | null;
  if (!el) return false;
  if (el.tagName === "INPUT" || el.tagName === "TEXTAREA") return !space || (el as HTMLInputElement).value !== "";
  if (el.tagName === "SELECT" || el.isContentEditable) return true;
  return (el.tagName === "BUTTON" || el.tagName === "A" || el.getAttribute("role") === "button") && el.matches(":focus-visible");
}

/** Hold Space to talk (let go to send), tap Space to talk hands-free, Space again to send now,
 *  Esc to stop talking or cancel, V for spoken replies. Returns an unbind. */
export function bindVoiceKeys(): () => void {
  let pressedAt = 0;
  const down = (e: KeyboardEvent) => {
    // mid-composition (Japanese, Chinese…) keys belong to the input method
    if (e.metaKey || e.ctrlKey || e.altKey || e.isComposing) return;
    const s = useVoice.getState();
    // while listening Space and Esc are always the voice's, even in a field
    if (e.code === "Space" && s.listening) {
      e.preventDefault();
      if (!e.repeat && s.mode === "auto") stopListening();
      return;
    }
    if (e.key === "Escape" && s.listening) {
      cancelListening();
      return;
    }
    if (typing(e.target, e.code === "Space")) {
      // typing now: a reply shouldn't reopen the mic as if the conversation were still spoken
      if (e.key.length === 1) lastHandsFree = 0;
      return;
    }
    if (e.code === "Space") {
      e.preventDefault();
      if (e.repeat) return;
      pressedAt = performance.now();
      void startListening("hold");
    } else if (e.key === "Escape") {
      if (s.listening) cancelListening();
      stopSpeaking();
    } else if (e.key === "v" || e.key === "V") {
      setReplies(!s.replies, true);
    }
  };
  const up = (e: KeyboardEvent) => {
    if (e.code !== "Space" || !pressedAt) return;
    const held = performance.now() - pressedAt;
    pressedAt = 0;
    const s = useVoice.getState();
    if (!s.listening || s.mode !== "hold") return;
    e.preventDefault();
    if (held < TAP_MS) keepListening();
    else stopListening();
  };
  // Space held when the window loses focus (Cmd-Tab, a click into another app) never sends its keyup:
  // treat leaving as letting go, or the mic would stay open with nobody holding it
  const away = () => {
    if (!pressedAt && useVoice.getState().mode !== "hold") return;
    pressedAt = 0;
    if (useVoice.getState().mode === "hold") stopListening();
  };
  const hidden = () => document.hidden && away();
  window.addEventListener("keydown", down);
  window.addEventListener("keyup", up);
  window.addEventListener("blur", away);
  document.addEventListener("visibilitychange", hidden);
  window.addEventListener("pagehide", closeMic);
  return () => {
    window.removeEventListener("keydown", down);
    window.removeEventListener("keyup", up);
    window.removeEventListener("blur", away);
    document.removeEventListener("visibilitychange", hidden);
    window.removeEventListener("pagehide", closeMic);
    closeMic();
  };
}
