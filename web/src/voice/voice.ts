// Bara's voice (Figma 19 Voice · talk to Bara). Hold Space to talk and let go to send, or tap Space (or
// the mic) and just talk: a pause at the end of what you said sends it. Ums and stutters are taken out
// before Bara sees it. Bara answers out loud through the engine's streamed speech (OpenAI when the
// engine has its key), with the words shown under the eyes; without it, the browser's own speech fills
// in, so nothing depends on one service. Replies are cut to one or two short sentences, the first one
// starts playing while the next downloads, talking again stops it (barge-in), and the time from the
// end of your speech to the first sound is kept in `latencyMs`.
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
  u.rate = 1.02;
  u.onstart = markFirstSound;
  u.onend = finished;
  u.onerror = () => useVoice.setState({ caption: null });
  speechSynthesis.speak(u);
}

/** Says a reply when replies are on (or `force`); the caption shows while it plays. `then` runs
 *  when it has been said through, which is how a spoken conversation hands the turn back. */
export function speak(text: string, force = false, then?: () => void): void {
  const clean = trimReply(text, askedWords);
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
/** After letting go, how long to wait for the recogniser's final words before sending what it has. */
const FINAL_WAIT_MS = 300;
/** Recording without a recogniser: a silence this long after speech ends the turn. */
const VAD_SILENCE_MS = 900;

let recognition: Recognition | null = null;
let recorder: MediaRecorder | null = null;
let chunks: Blob[] = [];
let cancelled = false;
/** One number per listening turn, so a late callback from an old turn does nothing. */
let turn = 0;
let delivered = 0;
let endTimer = 0;
let quietTimer = 0;
let finalTimer = 0;
let quietMs = QUIET_MS;
/** When the last spoken turn was sent hands-free; replies to it hand the mic straight back. */
let lastHandsFree = 0;

function recognitionClass(): (new () => Recognition) | null {
  const w = window as unknown as { SpeechRecognition?: new () => Recognition; webkitSpeechRecognition?: new () => Recognition };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

function clearTimers(): void {
  window.clearTimeout(endTimer);
  window.clearTimeout(quietTimer);
  window.clearTimeout(finalTimer);
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
  const target = useApp.getState().focusKey ? "bara:ask" : "bara:prompt";
  window.dispatchEvent(new CustomEvent(target, { detail: t }));
}

/** Hands-free: (re)start the clock that ends the turn once the speaker pauses. */
function armEndOfTurn(): void {
  const s = useVoice.getState();
  if (!s.listening || s.mode !== "auto") return;
  window.clearTimeout(endTimer);
  window.clearTimeout(quietTimer);
  const wait = endOfTurnMs(s.heard);
  if (wait === null) quietTimer = window.setTimeout(cancelListening, quietMs);
  else endTimer = window.setTimeout(stopListening, wait);
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
    deliver(text, id, handsFree);
  } catch (e) {
    useVoice.setState({ error: e instanceof Error ? e.message : "Couldn't hear that." });
  } finally {
    useVoice.setState({ transcribing: false });
  }
}

/** Watches the mic level so a recording (no recogniser) can tell speech from silence. */
function watchLevel(stream: MediaStream, id: number): () => void {
  const Ctx = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!Ctx) return () => {};
  const ctx = new Ctx();
  const analyser = ctx.createAnalyser();
  analyser.fftSize = 1024;
  ctx.createMediaStreamSource(stream).connect(analyser);
  const buf = new Float32Array(analyser.fftSize);
  const started = performance.now();
  let floor = 0.01;
  let spoke = false;
  let lastLoud = started;
  const tick = window.setInterval(() => {
    if (turn !== id) return;
    analyser.getFloatTimeDomainData(buf);
    let sum = 0;
    for (const v of buf) sum += v * v;
    const rms = Math.sqrt(sum / buf.length);
    const now = performance.now();
    // the first moment is room noise; after that the floor only drifts down
    if (now - started < 250) floor = Math.max(floor, rms);
    else if (rms < floor) floor = floor * 0.95 + rms * 0.05;
    if (rms > Math.max(0.02, floor * 2.5)) {
      spoke = true;
      lastLoud = now;
      useVoice.setState({ heard: useVoice.getState().heard || "…" });
    }
    if (useVoice.getState().mode !== "auto") return;
    if (spoke && now - lastLoud > VAD_SILENCE_MS) stopListening();
    else if (!spoke && now - started > quietMs) cancelListening();
  }, 50);
  return () => {
    window.clearInterval(tick);
    void ctx.close();
  };
}

async function record(id: number): Promise<void> {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
    if (turn !== id) {
      stream.getTracks().forEach((t) => t.stop());
      return;
    }
    // the level watcher below decides when a hands-free recording ends
    clearTimers();
    const rec = new MediaRecorder(stream);
    const unwatch = watchLevel(stream, id);
    recorder = rec;
    chunks = [];
    rec.ondataavailable = (e) => {
      if (e.data.size) chunks.push(e.data);
    };
    rec.onstop = () => {
      unwatch();
      stream.getTracks().forEach((t) => t.stop());
      if (recorder === rec) recorder = null;
      markSpeechEnd();
      const handsFree = useVoice.getState().mode === "auto";
      useVoice.setState({ listening: false, mode: null, heard: "" });
      if (!cancelled && chunks.length) void transcribe(new Blob(chunks, { type: rec.mimeType || "audio/webm" }), id, handsFree);
    };
    rec.start();
    // released before the mic opened: stop right away and send what there is
    if (!useVoice.getState().listening) rec.stop();
  } catch {
    useVoice.setState({ listening: false, error: "Microphone access is blocked." });
  }
}

/** Opens the mic. Hands-free ("auto") sends when the speaker pauses; "hold" sends when let go. */
export async function startListening(mode: ListenMode = "auto", opts: { quietMs?: number } = {}): Promise<void> {
  if (useVoice.getState().listening) return;
  // barge-in: talking while Bara talks stops it at once, before the mic even opens
  stopSpeaking();
  speechEndedAt = null;
  clearTimers();
  cancelled = false;
  quietMs = opts.quietMs ?? QUIET_MS;
  const id = ++turn;
  useVoice.setState({ listening: true, mode, heard: "", error: null });
  armEndOfTurn();
  const Rec = recognitionClass();
  if (Rec) {
    const r = new Rec();
    recognition = r;
    r.continuous = true;
    r.interimResults = true;
    r.lang = navigator.language || "en-US";
    r.onresult = (e) => {
      if (recognition !== r) return;
      let text = "";
      for (let i = 0; i < e.results.length; i++) text += e.results[i][0].transcript;
      useVoice.setState({ heard: cleanTranscript(text) });
      armEndOfTurn();
    };
    r.onerror = (e) => {
      if (recognition !== r) return;
      recognition = null;
      if (e.error === "not-allowed") {
        clearTimers();
        useVoice.setState({ listening: false, mode: null, error: "Microphone access is blocked." });
        return;
      }
      if (e.error === "aborted" || e.error === "no-speech") {
        clearTimers();
        useVoice.setState({ listening: false, mode: null });
        return;
      }
      // no recognition service here (common outside Chrome): record and let the engine listen
      if (useVoice.getState().listening) void record(id);
    };
    r.onend = () => {
      if (recognition !== r) return;
      recognition = null;
      clearTimers();
      markSpeechEnd();
      const { heard, mode } = useVoice.getState();
      useVoice.setState({ listening: false, mode: null });
      if (!cancelled) deliver(heard, id, mode === "auto");
    };
    try {
      r.start();
      return;
    } catch {
      recognition = null;
    }
  }
  await record(id);
}

/** A held press turned out to be a tap: keep listening, hands-free. */
export function keepListening(): void {
  if (!useVoice.getState().listening) return;
  useVoice.setState({ mode: "auto" });
  armEndOfTurn();
}

/** Stop and send what was said. */
export function stopListening(): void {
  clearTimers();
  const r = recognition;
  if (r) {
    // the recogniser can take a moment to settle its last words; don't make the speaker wait on it
    const id = turn;
    r.stop();
    finalTimer = window.setTimeout(() => {
      if (recognition !== r || turn !== id) return;
      recognition = null;
      const { heard, mode } = useVoice.getState();
      useVoice.setState({ listening: false, mode: null });
      r.abort();
      deliver(heard, id, mode === "auto");
    }, FINAL_WAIT_MS);
  } else if (recorder && recorder.state !== "inactive") recorder.stop();
  else useVoice.setState({ listening: false, mode: null });
}

/** Stop and throw it away (Esc). */
export function cancelListening(): void {
  cancelled = true;
  clearTimers();
  const r = recognition;
  recognition = null;
  r?.abort();
  if (recorder && recorder.state !== "inactive") recorder.stop();
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
