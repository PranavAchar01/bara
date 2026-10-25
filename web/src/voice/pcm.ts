// Bara's spoken lines, played as they arrive. The engine streams raw 24 kHz 16-bit PCM; each piece is
// scheduled on one shared AudioContext the moment it lands, so the first word plays after the first
// few hundredths of a second of audio instead of after the whole clip (an <audio> element buffers
// seconds of a stream before it starts). Short lines that played out in full are kept, so a line
// said again starts at once with no request at all.

const RATE = 24000;
/** Gather this much before the first sound, so the start doesn't stutter on tiny network pieces. */
const FIRST_SAMPLES = RATE / 20;
/** Later pieces are scheduled once they hold this much (or the stream ends). */
const NEXT_SAMPLES = RATE / 10;
/** A little headroom when (re)starting, so the first buffer isn't scheduled in the past. */
const LEAD_S = 0.02;

let shared: AudioContext | null = null;

/** The one AudioContext all lines (and the listening cue) play on. */
export function audioContext(): AudioContext | null {
  if (shared) return shared;
  const Ctx = typeof window === "undefined" ? undefined : (window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext);
  if (!Ctx) return null;
  shared = new Ctx({ latencyHint: "interactive" });
  return shared;
}

// Browsers start an AudioContext suspended until the page is touched: wake it on the first touch.
if (typeof window !== "undefined") {
  const wake = () => {
    const ctx = audioContext();
    if (ctx?.state === "suspended") void ctx.resume().catch(() => {});
  };
  for (const ev of ["pointerdown", "keydown", "touchend"]) window.addEventListener(ev, wake, { capture: true, passive: true });
}

const MAX_KEPT_CHARS = 240;
const KEPT_LINES = 48;
const kept = new Map<string, Float32Array>();
function keep(key: string, samples: Float32Array): void {
  kept.delete(key);
  kept.set(key, samples);
  while (kept.size > KEPT_LINES) kept.delete(kept.keys().next().value as string);
}

function floats(bytes: Uint8Array): Float32Array {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const out = new Float32Array(bytes.byteLength >> 1);
  for (let i = 0; i < out.length; i++) out[i] = view.getInt16(i * 2, true) / 32768;
  return out;
}

/**
 * One spoken line. The request starts as soon as the clip is made (so the next sentence downloads
 * while this one plays); `play()` starts the sound. Reports like an audio element: `onplaying` when
 * the first sound is heard, `onended` after the last, `onerror` if the audio never came.
 */
export class Clip {
  onplaying: (() => void) | null = null;
  onended: (() => void) | null = null;
  onerror: (() => void) | null = null;

  private abort = new AbortController();
  private pending: Float32Array[] = [];
  private pendingSamples = 0;
  private all: Float32Array[] = [];
  private decoded: AudioBuffer | null = null;
  private arrived = false;
  private got = 0;
  private failed = false;
  private playing = false;
  private stopped = false;
  private started = false;
  private next = 0;
  private live = new Set<AudioBufferSourceNode>();

  constructor(
    url: string,
    private key: string,
    headers: Record<string, string> = {},
  ) {
    const hit = kept.get(key);
    if (hit) {
      kept.delete(key);
      kept.set(key, hit);
      this.pending.push(hit);
      this.pendingSamples = hit.length;
      this.arrived = true;
      return;
    }
    void this.load(url, headers);
  }

  private async load(url: string, headers: Record<string, string>): Promise<void> {
    try {
      const res = await fetch(url, { headers, signal: this.abort.signal });
      if (!res.ok || !res.body) throw new Error(String(res.status));
      if (!/audio\/(pcm|l16)/i.test(res.headers.get("content-type") ?? "")) {
        // an older engine sends a whole encoded file: decode it and play it in one go
        const ctx = audioContext();
        if (!ctx) throw new Error("no audio");
        this.decoded = await ctx.decodeAudioData(await res.arrayBuffer());
        this.arrived = true;
        this.pump();
        return;
      }
      const reader = res.body.getReader();
      let carry: Uint8Array | null = null;
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        if (this.stopped) return;
        let bytes: Uint8Array = value;
        if (carry) {
          const joined: Uint8Array = new Uint8Array(carry.length + bytes.length);
          joined.set(carry);
          joined.set(bytes, carry.length);
          bytes = joined;
          carry = null;
        }
        // a piece can end halfway through a sample: hold the odd byte for the next piece
        if (bytes.length & 1) {
          carry = bytes.slice(-1);
          bytes = bytes.subarray(0, bytes.length - 1);
        }
        if (!bytes.length) continue;
        const f = floats(bytes);
        this.pending.push(f);
        this.pendingSamples += f.length;
        this.got += f.length;
        if (this.key.length <= MAX_KEPT_CHARS) this.all.push(f);
        this.pump();
      }
      this.arrived = true;
      if (!this.got) throw new Error("empty");
      if (this.all.length) {
        // the whole line is here: keep it, whether or not it has played yet
        const whole = new Float32Array(this.got);
        let at = 0;
        for (const p of this.all) {
          whole.set(p, at);
          at += p.length;
        }
        keep(this.key, whole);
        this.all = [];
      }
      this.pump();
    } catch {
      if (this.stopped) return;
      this.failed = true;
      this.all = [];
      if (this.playing) this.onerror?.();
    }
  }

  /** Starts the sound (now, or as soon as the first audio lands). Rejects when sound can't play. */
  async play(): Promise<void> {
    const ctx = audioContext();
    if (!ctx) throw new Error("no audio");
    if (ctx.state === "suspended") await ctx.resume();
    // still asleep: nothing on the page has been touched yet, and nothing can play
    if (ctx.state !== "running") throw new Error("audio blocked");
    this.playing = true;
    if (this.failed) {
      this.onerror?.();
      return;
    }
    this.pump();
  }

  /** Stops the sound and the download. */
  pause(): void {
    this.stopped = true;
    this.playing = false;
    this.abort.abort();
    for (const s of this.live) {
      s.onended = null;
      try {
        s.stop();
      } catch {
        // never started
      }
    }
    this.live.clear();
  }

  private pump(): void {
    if (!this.playing || this.stopped) return;
    const ctx = audioContext();
    if (!ctx) return;
    if (this.decoded) {
      const b = this.decoded;
      this.decoded = null;
      this.schedule(ctx, b);
    } else {
      const need = this.started ? NEXT_SAMPLES : FIRST_SAMPLES;
      if (!this.pendingSamples || (this.pendingSamples < need && !this.arrived)) return;
      const samples = new Float32Array(this.pendingSamples);
      let at = 0;
      for (const p of this.pending) {
        samples.set(p, at);
        at += p.length;
      }
      this.pending = [];
      this.pendingSamples = 0;
      const b = ctx.createBuffer(1, samples.length, RATE);
      b.copyToChannel(samples, 0);
      this.schedule(ctx, b);
    }
  }

  private schedule(ctx: AudioContext, buffer: AudioBuffer): void {
    const src = ctx.createBufferSource();
    src.buffer = buffer;
    src.connect(ctx.destination);
    // fell behind (the network paused): start again just ahead of now rather than in the past
    const when = Math.max(this.next, ctx.currentTime + LEAD_S);
    this.next = when + buffer.duration;
    if (!this.started) {
      this.started = true;
      const lead = (when - ctx.currentTime) * 1000;
      window.setTimeout(() => !this.stopped && this.onplaying?.(), Math.max(0, lead));
    }
    this.live.add(src);
    src.onended = () => {
      this.live.delete(src);
      if (this.stopped || this.live.size || !this.arrived || this.pendingSamples) return;
      this.stopped = true;
      this.onended?.();
    };
    src.start(when);
  }
}

/** A short, soft two-note "mm-hm": Bara heard you and is on it (the answer is on its way). */
export function hearCue(): void {
  const ctx = audioContext();
  if (!ctx || ctx.state !== "running") return;
  const t = ctx.currentTime + 0.005;
  const gain = ctx.createGain();
  gain.connect(ctx.destination);
  gain.gain.setValueAtTime(0, t);
  for (const [i, f] of [660, 880].entries()) {
    const at = t + i * 0.07;
    const o = ctx.createOscillator();
    o.type = "sine";
    o.frequency.setValueAtTime(f, at);
    o.connect(gain);
    gain.gain.setTargetAtTime(0.06, at, 0.008);
    gain.gain.setTargetAtTime(0, at + 0.045, 0.02);
    o.start(at);
    o.stop(at + 0.14);
  }
}
