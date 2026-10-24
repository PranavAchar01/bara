// Bara's voice (Figma 19 Voice · talk to Bara). Hold Space or tap the eyes to talk; Bara answers
// out loud through the engine's ElevenLabs stream, with the words shown under the eyes. Without
// the engine's voice, the browser's own speech fills in, so nothing depends on one service.
import { create } from "zustand";
import { authHeaders, serverUrl } from "../net/mode";
import { useApp } from "../state/store";

export interface VoiceState {
  /** The mic is open. */
  listening: boolean;
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
  heard: "",
  transcribing: false,
  caption: null,
  replies: storedReplies(),
  error: null,
}));

export function setReplies(on: boolean): void {
  useVoice.setState({ replies: on });
  try {
    localStorage.setItem(STORE_KEY, on ? "1" : "0");
  } catch {
    // storage blocked: the choice lasts for this page
  }
  if (!on) stopSpeaking();
}

// ---------------------------------------------------------------- speaking

let audio: HTMLAudioElement | null = null;
let engineVoice: boolean | null = null;

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
  if (audio) {
    audio.pause();
    audio.src = "";
    audio = null;
  }
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

function speakInBrowser(text: string): void {
  if (typeof speechSynthesis === "undefined") {
    useVoice.setState({ caption: null });
    return;
  }
  const u = new SpeechSynthesisUtterance(text);
  const v = browserVoice();
  if (v) u.voice = v;
  u.rate = 1.02;
  u.onend = () => useVoice.setState({ caption: null });
  u.onerror = () => useVoice.setState({ caption: null });
  speechSynthesis.speak(u);
}

/** Says a reply when replies are on (or `force`); the caption shows while it plays. */
export function speak(text: string, force = false): void {
  const clean = text.trim();
  if (!clean || (!force && !useVoice.getState().replies)) return;
  stopSpeaking();
  useVoice.setState({ caption: clean });
  void engineCanSpeak().then((ok) => {
    if (useVoice.getState().caption !== clean) return;
    if (!ok) {
      speakInBrowser(clean);
      return;
    }
    // GET, so the audio element plays the stream as it arrives instead of waiting for the file
    const a = new Audio(serverUrl(`/v1/tts?text=${encodeURIComponent(clean)}`));
    audio = a;
    a.onended = () => {
      if (audio === a) useVoice.setState({ caption: null });
    };
    a.onerror = () => {
      if (audio !== a) return;
      engineVoice = false;
      speakInBrowser(clean);
    };
    void a.play().catch(() => {
      if (audio === a) speakInBrowser(clean);
    });
  });
}

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

let recognition: Recognition | null = null;
let recorder: MediaRecorder | null = null;
let chunks: Blob[] = [];
let cancelled = false;

function recognitionClass(): (new () => Recognition) | null {
  const w = window as unknown as { SpeechRecognition?: new () => Recognition; webkitSpeechRecognition?: new () => Recognition };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

/** Where a finished utterance goes: the part in focus if there is one, otherwise the prompt. */
function deliver(text: string): void {
  const t = text.trim();
  if (!t) return;
  if (!useVoice.getState().replies) setReplies(true);
  const target = useApp.getState().focusKey ? "bara:ask" : "bara:prompt";
  window.dispatchEvent(new CustomEvent(target, { detail: t }));
}

async function transcribe(blob: Blob): Promise<void> {
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
    useVoice.setState({ heard: text });
    deliver(text);
  } catch (e) {
    useVoice.setState({ error: e instanceof Error ? e.message : "Couldn't hear that." });
  } finally {
    useVoice.setState({ transcribing: false });
  }
}

async function record(): Promise<void> {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const rec = new MediaRecorder(stream);
    recorder = rec;
    chunks = [];
    rec.ondataavailable = (e) => {
      if (e.data.size) chunks.push(e.data);
    };
    rec.onstop = () => {
      stream.getTracks().forEach((t) => t.stop());
      recorder = null;
      useVoice.setState({ listening: false });
      if (!cancelled && chunks.length) void transcribe(new Blob(chunks, { type: rec.mimeType || "audio/webm" }));
    };
    rec.start();
    // released before the mic opened: stop right away and send what there is
    if (!useVoice.getState().listening) rec.stop();
  } catch {
    useVoice.setState({ listening: false, error: "Microphone access is blocked." });
  }
}

export async function startListening(): Promise<void> {
  if (useVoice.getState().listening) return;
  stopSpeaking();
  cancelled = false;
  useVoice.setState({ listening: true, heard: "", error: null });
  const Rec = recognitionClass();
  if (Rec) {
    const r = new Rec();
    recognition = r;
    r.continuous = true;
    r.interimResults = true;
    r.lang = navigator.language || "en-US";
    r.onresult = (e) => {
      let text = "";
      for (let i = 0; i < e.results.length; i++) text += e.results[i][0].transcript;
      useVoice.setState({ heard: text.trim() });
    };
    r.onerror = (e) => {
      if (recognition !== r) return;
      recognition = null;
      if (e.error === "not-allowed") {
        useVoice.setState({ listening: false, error: "Microphone access is blocked." });
        return;
      }
      // no recognition service here (common outside Chrome): record and let the engine listen
      if (e.error !== "aborted" && e.error !== "no-speech" && useVoice.getState().listening) void record();
    };
    r.onend = () => {
      if (recognition !== r) return;
      recognition = null;
      const heard = useVoice.getState().heard;
      useVoice.setState({ listening: false });
      if (!cancelled) deliver(heard);
    };
    try {
      r.start();
      return;
    } catch {
      recognition = null;
    }
  }
  await record();
}

/** Stop and send what was said. */
export function stopListening(): void {
  if (recognition) recognition.stop();
  else if (recorder && recorder.state !== "inactive") recorder.stop();
  else useVoice.setState({ listening: false });
}

/** Stop and throw it away (Esc). */
export function cancelListening(): void {
  cancelled = true;
  const r = recognition;
  recognition = null;
  r?.abort();
  if (recorder && recorder.state !== "inactive") recorder.stop();
  useVoice.setState({ listening: false, heard: "" });
}

/** Space belongs to the page here: a text field, or a control reached by keyboard (Space presses it). */
function typing(t: EventTarget | null): boolean {
  const el = t as HTMLElement | null;
  if (!el) return false;
  if (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable) return true;
  return (el.tagName === "BUTTON" || el.tagName === "A" || el.getAttribute("role") === "button") && el.matches(":focus-visible");
}

/** Hold Space to talk, Esc to stop talking or cancel, V for spoken replies. Returns an unbind. */
export function bindVoiceKeys(): () => void {
  const down = (e: KeyboardEvent) => {
    if (typing(e.target) || e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.code === "Space") {
      e.preventDefault();
      if (!e.repeat) void startListening();
    } else if (e.key === "Escape") {
      if (useVoice.getState().listening) cancelListening();
      stopSpeaking();
    } else if (e.key === "v" || e.key === "V") {
      setReplies(!useVoice.getState().replies);
    }
  };
  const up = (e: KeyboardEvent) => {
    if (e.code === "Space" && useVoice.getState().listening) {
      e.preventDefault();
      stopListening();
    }
  };
  window.addEventListener("keydown", down);
  window.addEventListener("keyup", up);
  return () => {
    window.removeEventListener("keydown", down);
    window.removeEventListener("keyup", up);
  };
}
