// Bara's voice (Figma 19 Voice · talk to Bara). Hold Space to talk and let go to send, or tap Space (or
// the mic) and just talk: a pause at the end of what you said sends it. Ums and stutters are taken out
// before Bara sees it. Bara answers out loud through the engine's voice stream, with the words shown
// under the eyes; without it, the browser's own speech fills in, so nothing depends on one service.
import { create } from "zustand";
import { authHeaders, serverUrl } from "../net/mode";
import { showToast, useApp } from "../state/store";
import { cleanTranscript, endOfTurnMs } from "./turn";

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
}));

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

function ttsAudio(line: string): HTMLAudioElement {
  const a = new Audio(serverUrl(`/v1/tts?text=${encodeURIComponent(line)}`));
  a.preload = "auto";
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
  for (const a of [audio, upNext]) {
    if (!a) continue;
    a.pause();
    a.src = "";
  }
  audio = null;
  upNext = null;
  afterSpeech = null;
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
  useVoice.setState({ caption: null });
  const then = afterSpeech;
  afterSpeech = null;
  then?.();
}

function speakInBrowser(text: string): void {
  if (typeof speechSynthesis === "undefined") {
    finished();
    return;
  }
  const u = new SpeechSynthesisUtterance(text);
  const v = browserVoice();
  if (v) u.voice = v;
  u.rate = 1.1;
  u.onend = finished;
  u.onerror = () => useVoice.setState({ caption: null });
  speechSynthesis.speak(u);
}

/** Says a reply when replies are on (or `force`); the caption shows while it plays. `then` runs
 *  when it has been said through, which is how a spoken conversation hands the turn back. */
export function speak(text: string, force = false, then?: () => void): void {
  const clean = text.trim();
  if (!clean || (!force && !useVoice.getState().replies)) return;
  stopSpeaking();
  afterSpeech = then ?? null;
  useVoice.setState({ caption: clean });
  void engineCanSpeak().then((ok) => {
    if (useVoice.getState().caption !== clean) return;
    if (!ok) {
      speakInBrowser(clean);
      return;
    }
    // GET, so the audio element plays the stream as it arrives instead of waiting for the file
    const lines = sentences(clean);
    const play = (i: number, a: HTMLAudioElement) => {
      audio = a;
      upNext = i + 1 < lines.length ? ttsAudio(lines[i + 1]) : null;
      a.onended = () => {
        if (audio !== a) return;
        if (upNext) play(i + 1, upNext);
        else finished();
      };
      a.onerror = () => {
        if (audio !== a) return;
        engineVoice = false;
        speakInBrowser(lines.slice(i).join(" "));
      };
      void a.play().catch(() => {
        if (audio === a) speakInBrowser(lines.slice(i).join(" "));
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
  /** The level watcher is running (the mic opened). */
  metered: boolean;
  unwatch: () => void;
  done: boolean;
}

let cur: Turn | null = null;
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
function deliver(text: string, id: number, handsFree: boolean): void {
  if (delivered === id) return;
  delivered = id;
  const t = cleanTranscript(text);
  if (!t) return;
  lastHandsFree = handsFree ? performance.now() : 0;
  if (!useVoice.getState().replies) setReplies(true);
  const target = useApp.getState().focusKey ? "bara:ask" : "bara:prompt";
  window.dispatchEvent(new CustomEvent(target, { detail: t }));
}

async function transcribe(blob: Blob, id: number, handsFree: boolean): Promise<void> {
  useVoice.setState({ transcribing: true });
  try {
    const build = useApp.getState().build?.build_id;
    const res = await fetch(serverUrl(`/v1/stt${build ? `?build_id=${encodeURIComponent(build)}` : ""}`), {
      method: "POST",
      headers: { ...authHeaders(), "content-type": blob.type || "audio/webm" },
      body: blob,
    });
    if (!res.ok) throw new Error(`Couldn't write that down (${res.status}).`);
    const text = ((await res.json()) as { text?: string }).text ?? "";
    useVoice.setState({ heard: cleanTranscript(text) });
    if (!cleanTranscript(text)) useVoice.setState({ error: "Didn't catch that. Try again?" });
    deliver(text, id, handsFree);
  } catch (e) {
    useVoice.setState({ error: e instanceof Error ? e.message : "Couldn't hear that." });
  } finally {
    useVoice.setState({ transcribing: false });
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

async function openMic(t: Turn): Promise<void> {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
    if (t.done) {
      stream.getTracks().forEach((x) => x.stop());
      return;
    }
    const rec = new MediaRecorder(stream);
    rec.ondataavailable = (e) => {
      if (e.data.size) t.chunks.push(e.data);
    };
    const unwatch = watchLevel(stream, t);
    t.unwatch = () => {
      unwatch();
      stream.getTracks().forEach((x) => x.stop());
    };
    t.recorder = rec;
    rec.start();
  } catch {
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
  if (cur === t) cur = null;
  const handsFree = useVoice.getState().mode === "auto";
  useVoice.setState({ listening: false, mode: null, ...(send ? {} : { heard: "" }) });
  const r = t.recognition;
  t.recognition = null;
  const recording = stopRecording(t);
  if (!send) {
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
  const heard = useVoice.getState().heard;
  const blob = await recording;
  if (heard) deliver(heard, t.id, handsFree);
  else if (t.spoke && blob) await transcribe(blob, t.id, handsFree);
  else if (t.metered && t.loudest < DEAD_MIC_RMS) useVoice.setState({ error: "No sound from your mic. Check which input is selected." });
}

/** Opens the mic. Hands-free ("auto") sends when the speaker pauses; "hold" sends when let go. */
export async function startListening(mode: ListenMode = "auto", opts: { quietMs?: number } = {}): Promise<void> {
  if (useVoice.getState().listening) return;
  stopSpeaking();
  quietMs = opts.quietMs ?? QUIET_MS;
  const t: Turn = { id: ++turns, recognition: null, recorder: null, chunks: [], started: performance.now(), spoke: false, lastLoud: 0, loudest: 0, metered: false, unwatch: () => {}, done: false };
  cur = t;
  useVoice.setState({ listening: true, mode, heard: "", error: null });
  armQuiet(t);
  const Rec = recognitionClass();
  if (Rec) {
    const r = new Rec();
    r.continuous = true;
    r.interimResults = true;
    r.lang = navigator.language || "en-US";
    r.onresult = (e) => {
      if (t.done) return;
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
function typing(t: EventTarget | null): boolean {
  const el = t as HTMLElement | null;
  if (!el) return false;
  if (el.tagName === "INPUT" || el.tagName === "TEXTAREA") return (el as HTMLInputElement).value !== "";
  if (el.tagName === "SELECT" || el.isContentEditable) return true;
  return (el.tagName === "BUTTON" || el.tagName === "A" || el.getAttribute("role") === "button") && el.matches(":focus-visible");
}

/** Hold Space to talk (let go to send), tap Space to talk hands-free, Space again to send now,
 *  Esc to stop talking or cancel, V for spoken replies. Returns an unbind. */
export function bindVoiceKeys(): () => void {
  let pressedAt = 0;
  const down = (e: KeyboardEvent) => {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
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
    if (typing(e.target)) return;
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
  window.addEventListener("keydown", down);
  window.addEventListener("keyup", up);
  return () => {
    window.removeEventListener("keydown", down);
    window.removeEventListener("keyup", up);
  };
}
