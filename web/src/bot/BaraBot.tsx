// The Bara bot: a dark oval with two eyes, nothing else. All the life is in
// motion: the eyes' size, lids, happy cheeks, gaze, darting saccades and
// blinks, and the oval's breath, squash, stretch, tilt and hops. A mood sets
// the resting face, the stage's activity drives the gaze, each event fires a
// one-shot emote, and every change goes through springs, so it morphs from one
// feeling to the next and never stops moving. One SVG, mutated per frame from
// refs; React only renders when the mood or the bubbles change.
//
// Bubbles (on by default, ?bubbles=0 turns them off): a thought cloud of tiny icons while it
// thinks, and a one-line speech bubble typed out while its eyes bounce with
// the words.
import { useEffect, useId, useRef, useState } from "react";
import { useApp } from "../state/store";
import { emoteFor, moodOf, speechFor, THOUGHTS, type Activity, type Emote, type Mood, type ThoughtIcon } from "./mood";
import { clamp, lerp, PRESETS, reducedMotion, Spring, wander } from "./spring";
import { ThoughtGlyph } from "./glyphs";
import "./bot.css";

/** Eye and oval pose; every field is a spring. */
interface Pose {
  w: number; // eye width
  h: number; // eye height
  gap: number; // eye centre distance
  ey: number; // eye centre height
  loL: number; // left eye lid coverage at the outer corner (0..1 of eye height)
  liL: number; // ... inner corner
  loR: number;
  liR: number;
  happy: number; // cheeks push up into ^ ^
  sL: number; // eye scale
  sR: number;
  tilt: number; // deg
  sx: number; // oval squash and stretch
  sy: number;
  by: number; // oval lift (negative is up)
  dim: number; // eye dimming
  flat: number; // eyes as flat lines (offline)
}

const BASE: Pose = { w: 13, h: 19, gap: 25, ey: 0, loL: 0, liL: 0, loR: 0, liR: 0, happy: 0, sL: 1, sR: 1, tilt: 0, sx: 1, sy: 1, by: 0, dim: 0, flat: 0 };

const MOOD: Record<Mood, Partial<Pose>> = {
  idle: {},
  listening: { w: 14.5, h: 22, sx: 1.02, sy: 1.04 },
  thinking: { h: 17, loL: 0.16, liL: 0.28, loR: 0.16, liR: 0.28 },
  working: { w: 14, h: 14, loL: 0.06, liL: 0.42, loR: 0.06, liR: 0.42 },
  asking: { sL: 1.14, sR: 0.84, tilt: -9, h: 20 },
  happy: { happy: 1, w: 15, h: 20 },
  worried: { loL: 0.42, loR: 0.42, liL: 0.04, liR: 0.04, h: 18, sL: 0.95, sR: 0.95 },
  sad: { h: 15, loL: 0.55, loR: 0.55, liL: 0.08, liR: 0.08, dim: 0.25, sy: 0.94, by: 3, ey: 2 },
  sleepy: { h: 9, loL: 0.45, liL: 0.45, loR: 0.45, liR: 0.45, sy: 0.97, by: 1.5 },
  offline: { flat: 1, dim: 0.6, sy: 0.95, by: 1.5 },
  connecting: { flat: 0.55, h: 8, w: 8 },
};

const ACTIVITY: Record<Activity, Partial<Pose>> = {
  read: { h: 16, loL: 0.18, liL: 0.18, loR: 0.18, liR: 0.18 },
  search: { w: 14.5, h: 19 },
  pick: { w: 14, h: 20 },
  arrange: { h: 17, loL: 0.1, liL: 0.3, loR: 0.1, liR: 0.3 },
  sculpt: { sL: 1.12, sR: 0.78, loR: 0.45, liR: 0.4, tilt: 5 },
  route: { h: 13, loL: 0.28, liL: 0.42, loR: 0.28, liR: 0.42 },
  type: { h: 14, loL: 0.2, liL: 0.32, loR: 0.2, liR: 0.32 },
  admire: { w: 16, h: 23 },
};

/** One-shot faces, held for ms then released back to the mood. */
const EMOTE: Record<Emote, { pose: Partial<Pose>; ms: number }> = {
  nod: { pose: {}, ms: 300 },
  pop: { pose: { w: 15, h: 22 }, ms: 260 },
  hop: { pose: { happy: 0.4 }, ms: 600 },
  wince: { pose: { h: 6, loL: 0.55, liL: 0.55, loR: 0.55, liR: 0.55 }, ms: 520 },
  surprise: { pose: { w: 16, h: 27, sy: 1.06 }, ms: 700 },
  delight: { pose: { happy: 1, w: 16, h: 21 }, ms: 1300 },
  shake: { pose: { loL: 0.35, loR: 0.35 }, ms: 800 },
  yawn: { pose: { h: 3, sy: 1.12, sx: 0.94, by: -2 }, ms: 1500 },
};

/** Thought and speech bubbles: on unless ?bubbles=0 (remembered) turned them off. */
export function botBubbles(): boolean {
  const q = new URLSearchParams(window.location.search).get("bubbles");
  if (q === "1" || q === "0") {
    try {
      localStorage.setItem("bara.bubbles", q);
    } catch {
      // storage blocked: the URL still decides for this page
    }
    return q === "1";
  }
  try {
    return localStorage.getItem("bara.bubbles") !== "0";
  } catch {
    return true;
  }
}

const VOWELS = /[aeiouyAEIOUY]/;
/** How long a line stays up after it is typed out. */
const SPEECH_HOLD_MS = 1500;
/** At most one line this often from the stream; done, failed and questions always speak. */
const SPEECH_GAP_MS = 3000;
const ALWAYS_SPEAK = new Set(["build.done", "build.failed", "clarify.request"]);
/** The oval, in viewBox units. */
const OVAL_W = 88;
const OVAL_H = 62;

export interface BaraBotProps {
  size?: number;
  /** Overrides the store (BotLab): mood, activity and emotes come from here instead. */
  mood?: Mood;
  activity?: Activity | null;
  /** Bumped to fire an emote (BotLab). */
  emote?: { kind: Emote; n: number } | null;
  /** Show a line in the speech bubble (BotLab). */
  say?: { text: string; n: number } | null;
  /** The user is typing in the prompt next to the bot; bump typingNonce per key. */
  typing?: boolean;
  typingNonce?: number;
  bubbles?: boolean;
  className?: string;
}

/** The bot, driven by the build (default) or by props (BotLab). */
export function BaraBot(props: BaraBotProps) {
  const size = props.size ?? 32;
  const conn = useApp((s) => s.conn);
  const buildStatus = useApp((s) => s.build?.status ?? null);
  const stage = useApp((s) => Object.values(s.view.stages).find((v) => v.status === "active")?.id ?? null);
  const [quietSince, setQuietSince] = useState(() => performance.now());
  const [doneAt, setDoneAt] = useState<number | null>(null);
  const [now, setNow] = useState(() => performance.now());
  const [emote, setEmote] = useState<{ kind: Emote; n: number } | null>(null);
  const [speech, setSpeech] = useState<{ text: string; n: number } | null>(null);

  // Mood ticks over slowly (sleepy after a quiet spell, happy fading after done).
  useEffect(() => {
    const id = window.setInterval(() => setNow(performance.now()), 1000);
    return () => window.clearInterval(id);
  }, []);
  useEffect(() => {
    if (buildStatus === "done") setDoneAt(performance.now());
  }, [buildStatus]);

  // Every incoming event can fire an emote and, now and then, a line of speech.
  useEffect(() => {
    if (props.mood) return;
    let seen = useApp.getState().log.at(-1)?.id ?? 0;
    let n = 0;
    let lastSpoke = 0;
    return useApp.subscribe((s) => {
      const fresh = s.log.filter((e) => e.id > seen && e.dir === "in");
      if (!fresh.length) return;
      seen = s.log.at(-1)?.id ?? seen;
      setQuietSince(performance.now());
      for (const e of fresh) {
        const em = emoteFor(e);
        if (em) setEmote({ kind: em, n: ++n });
        const line = speechFor(e);
        const nowMs = performance.now();
        // A build streams dozens of parts: say one line now and then, not one per event.
        if (line && (ALWAYS_SPEAK.has(e.type) || nowMs - lastSpoke > SPEECH_GAP_MS)) {
          lastSpoke = nowMs;
          setSpeech({ text: line, n: ++n });
        }
      }
    });
  }, [props.mood]);
  useEffect(() => {
    if (props.typing) setQuietSince(performance.now());
  }, [props.typing, props.typingNonce]);

  const derived = moodOf({
    conn,
    buildStatus,
    stage,
    typing: !!props.typing,
    quietMs: now - quietSince,
    sinceDoneMs: doneAt != null ? now - doneAt : null,
  });
  const mood = props.mood ?? derived.mood;
  const activity = props.mood ? (props.activity ?? null) : derived.activity;

  return (
    <BotFace
      size={size}
      mood={mood}
      activity={activity}
      emote={props.emote ?? emote}
      say={props.say ?? speech}
      typingNonce={props.typingNonce ?? 0}
      bubbles={props.bubbles ?? false}
      className={props.className}
    />
  );
}

interface FaceProps {
  size: number;
  mood: Mood;
  activity: Activity | null;
  emote: { kind: Emote; n: number } | null;
  say: { text: string; n: number } | null;
  typingNonce: number;
  bubbles: boolean;
  className?: string;
}

function BotFace(props: FaceProps) {
  const { size, mood, activity, bubbles } = props;
  const svg = useRef<SVGSVGElement>(null);
  const uid = useId().replace(/:/g, "");
  const live = useRef({ mood, activity, speaking: false, syllable: 0, emote: null as Emote | null, emoteUntil: 0 });
  live.current.mood = mood;
  live.current.activity = activity;

  // Speech: typed out; each letter gives the eyes a beat to bounce on.
  const [typed, setTyped] = useState("");
  const [speechOn, setSpeechOn] = useState(false);
  useEffect(() => {
    const s = props.say;
    if (!s) return;
    const L = live.current;
    let i = 0;
    setSpeechOn(true);
    setTyped("");
    L.speaking = true;
    const reduced = reducedMotion();
    const step = window.setInterval(() => {
      i = reduced ? s.text.length : i + 1;
      setTyped(s.text.slice(0, i));
      const ch = s.text[i - 1] ?? " ";
      L.syllable = VOWELS.test(ch) ? 1 : ch === " " || /[.,!?…]/.test(ch) ? 0 : 0.4;
      if (i >= s.text.length) {
        window.clearInterval(step);
        L.speaking = false;
        L.syllable = 0;
      }
    }, 34);
    const hide = window.setTimeout(() => setSpeechOn(false), 34 * s.text.length + SPEECH_HOLD_MS);
    return () => {
      window.clearInterval(step);
      window.clearTimeout(hide);
      L.speaking = false;
      L.syllable = 0;
    };
  }, [props.say]);

  // Emotes hold their face for a while; impulses give them weight.
  const kick = useRef<((e: Emote) => void) | null>(null);
  useEffect(() => {
    const e = props.emote;
    if (!e) return;
    live.current.emote = e.kind;
    live.current.emoteUntil = performance.now() + EMOTE[e.kind].ms;
    kick.current?.(e.kind);
  }, [props.emote]);
  useEffect(() => {
    if (props.typingNonce) kick.current?.("pop");
  }, [props.typingNonce]);

  useEffect(() => {
    const root = svg.current;
    if (!root) return;
    const q = <T extends Element>(sel: string) => root.querySelector(sel) as T;
    const rig = q<SVGGElement>(".bb-rig");
    const face = q<SVGGElement>(".bb-face");
    const eyes = [0, 1].map((i) => ({
      g: q<SVGGElement>(`.bb-eye${i}`),
      white: q<SVGRectElement>(`.bb-eye${i} .bb-white`),
      lid: q<SVGPathElement>(`.bb-eye${i} .bb-lid`),
      cheek: q<SVGEllipseElement>(`.bb-eye${i} .bb-cheek`),
      clip: q<SVGRectElement>(`.bb-clip${i} rect`),
    }));

    const pose = Object.fromEntries(
      (Object.keys(BASE) as (keyof Pose)[]).map((k) => [k, new Spring(BASE[k], k === "tilt" || k === "by" ? PRESETS.bouncy : PRESETS.smooth)]),
    ) as Record<keyof Pose, Spring>;
    const gx = new Spring(0, PRESETS.snappy);
    const gy = new Spring(0, PRESETS.snappy);
    const blinkS = new Spring(0, PRESETS.blink);
    const squash = new Spring(0, PRESETS.wobbly); // extra squash on impacts
    const beat = new Spring(0, PRESETS.snappy); // speech bounce

    let pointer: { x: number; y: number } | null = null;
    const onMove = (ev: PointerEvent) => {
      pointer = { x: ev.clientX, y: ev.clientY };
    };
    window.addEventListener("pointermove", onMove, { passive: true });

    kick.current = (e: Emote) => {
      if (reducedMotion()) return;
      if (e === "nod") pose.by.impulse(26);
      if (e === "pop") squash.impulse(4.5);
      if (e === "hop" || e === "delight") {
        pose.by.impulse(-120);
        window.setTimeout(() => squash.impulse(-5), 260);
      }
      if (e === "surprise") pose.by.impulse(-60);
      if (e === "wince") squash.impulse(-4);
      if (e === "shake") {
        pose.tilt.impulse(260);
        window.setTimeout(() => pose.tilt.impulse(-420), 140);
        window.setTimeout(() => pose.tilt.impulse(320), 280);
      }
    };

    let nextBlink = performance.now() + 1500;
    let doubleBlink = false;
    let nextSaccade = 0;
    let sacX = 0;
    let sacY = 0;
    let glance = 0; // looking up at the thought bubble
    let last = performance.now();
    let raf = 0;
    const reduced = reducedMotion();

    const frame = (nowMs: number) => {
      const dt = Math.min(0.05, (nowMs - last) / 1000);
      last = nowMs;
      const t = nowMs / 1000;
      const L = live.current;
      const em = L.emote && nowMs < L.emoteUntil ? L.emote : null;

      // Targets: base, then mood, then activity (when the mood lets it act), then the emote.
      const target: Pose = { ...BASE, ...MOOD[L.mood] };
      if (L.activity && (L.mood === "working" || L.mood === "thinking" || L.mood === "happy")) Object.assign(target, ACTIVITY[L.activity]);
      if (em) Object.assign(target, EMOTE[em].pose);

      // Breathing: slow, always.
      const breathRate = L.mood === "sleepy" ? 0.18 : L.mood === "working" ? 0.42 : 0.28;
      const breath = Math.sin(t * Math.PI * 2 * breathRate);
      target.sy += 0.022 * breath;
      target.sx -= 0.014 * breath;
      target.by += 0.8 * breath;

      // Gaze: the pointer when it is attending to the user, the activity's path otherwise.
      let lookX = 0.25 * wander(t * 0.35, 1);
      let lookY = 0.2 * wander(t * 0.3, 2);
      const attends = L.mood === "idle" || L.mood === "listening" || L.mood === "asking" || L.mood === "happy";
      if (attends && pointer) {
        const r = root.getBoundingClientRect();
        const dx = pointer.x - (r.left + r.width / 2);
        const dy = pointer.y - (r.top + r.height / 2);
        const d = Math.hypot(dx, dy) || 1;
        const reach = clamp(d / 220, 0, 1);
        lookX = (dx / d) * reach;
        lookY = (dy / d) * reach * 0.8;
      }
      switch (L.activity && !attends ? L.activity : L.mood === "happy" && L.activity === "admire" ? "admire" : null) {
        case "read": {
          // Lines of text: left to right, then a quick return one line down.
          const ph = (t / 1.3) % 1;
          const line = Math.floor(t / 1.3) % 3;
          lookX = ph < 0.85 ? lerp(-0.8, 0.8, ph / 0.85) : 0.8 - (ph - 0.85) * 10;
          lookY = -0.25 + line * 0.25;
          break;
        }
        case "search":
          lookX = 0.9 * Math.sin(t * 1.5);
          lookY = -0.15 + 0.3 * Math.sin(t * 0.8 + 1);
          target.tilt += lookX * 5;
          break;
        case "pick": {
          const spots = [
            [-0.7, 0.2],
            [0.1, -0.4],
            [0.75, 0.15],
          ];
          const s = spots[Math.floor(t / 0.75) % 3];
          lookX = s[0];
          lookY = s[1];
          break;
        }
        case "arrange": {
          const k = Math.floor(t / 0.45) % 6;
          lookX = -0.7 + (k % 3) * 0.7;
          lookY = k < 3 ? -0.2 : 0.35;
          break;
        }
        case "sculpt":
          lookX = 0.55 * Math.cos(t * 0.9);
          lookY = 0.4 * Math.sin(t * 0.9);
          break;
        case "route":
          lookX = Math.sin(t * 2.1);
          lookY = 0.45 * Math.sin(t * 4.2);
          break;
        case "type":
          lookX = 0.15 * Math.sin(t * 7);
          lookY = 0.6;
          if (!reduced) target.by += 0.7 * Math.abs(Math.sin(t * 9));
          break;
        case "admire":
          lookX = 0.6 * Math.sin(t * 0.7);
          lookY = -0.3 + 0.2 * Math.sin(t * 1.3);
          break;
        default:
          break;
      }
      if (L.mood === "thinking" && !L.activity) {
        lookX = 0.55;
        lookY = -0.7;
      }
      if (L.mood === "sad" || L.mood === "offline") lookY = 0.6;
      if (L.mood === "sleepy") lookY = 0.4;
      if (L.mood === "connecting") {
        // Waiting: the two eyes take turns, like a loading pulse.
        target.sL = 1 + 0.35 * Math.max(0, Math.sin(t * 5));
        target.sR = 1 + 0.35 * Math.max(0, Math.sin(t * 5 - 1.6));
      }

      // Glance up at the thought bubble now and then.
      if (bubbles && (L.mood === "thinking" || L.mood === "working") && !L.speaking) {
        if (nowMs > glance + 4200) glance = nowMs;
        if (nowMs - glance < 700) {
          lookX = 0.75;
          lookY = -0.9;
        }
      }
      // Micro-saccades: small quick jumps of the gaze, the strongest "alive" cue.
      if (!reduced && nowMs > nextSaccade) {
        sacX = (Math.random() - 0.5) * 0.22;
        sacY = (Math.random() - 0.5) * 0.16;
        nextSaccade = nowMs + 350 + Math.random() * 900;
      }
      gx.target = clamp(lookX + sacX, -1, 1);
      gy.target = clamp(lookY + sacY, -1, 1);

      // Blinks: irregular, sometimes doubled; heavy and slow when sleepy.
      if (nowMs > nextBlink && L.mood !== "offline" && L.mood !== "connecting" && em !== "wince") {
        blinkS.target = 1;
        window.setTimeout(() => (blinkS.target = 0), L.mood === "sleepy" ? 260 : 90);
        if (!doubleBlink && Math.random() < 0.18) {
          doubleBlink = true;
          nextBlink = nowMs + 260;
        } else {
          doubleBlink = false;
          nextBlink = nowMs + (L.mood === "sleepy" ? 1800 : 2000) + Math.random() * 3600;
        }
      }

      // Talking: the eyes bounce on each syllable and the oval breathes with it.
      beat.target = L.speaking ? L.syllable : 0;

      for (const k of Object.keys(pose) as (keyof Pose)[]) {
        pose[k].target = target[k];
        pose[k].step(dt);
      }
      for (const s of [gx, gy, blinkS, squash, beat]) s.step(dt);

      const p = Object.fromEntries((Object.keys(pose) as (keyof Pose)[]).map((k) => [k, pose[k].value])) as unknown as Pose;
      const talk = reduced ? 0 : beat.value;
      const sq = squash.value * 0.02 + talk * 0.03;
      const sx = p.sx + sq;
      const sy = p.sy - sq;
      rig.setAttribute("transform", `translate(0 ${(p.by - talk * 1.5).toFixed(2)}) rotate(${p.tilt.toFixed(2)}) scale(${sx.toFixed(3)} ${sy.toFixed(3)})`);

      // The eyes trail the oval a touch (follow-through) and lean into their gaze.
      const lagY = -pose.by.velocity * 0.012;
      face.setAttribute("transform", `translate(${(gx.value * 9).toFixed(2)} ${(gy.value * 6 + lagY - talk * 1.2).toFixed(2)})`);
      const openness = (1 - 0.94 * blinkS.value) * (1 - p.flat);
      for (let i = 0; i < 2; i++) {
        const e = eyes[i];
        const side = i === 0 ? -1 : 1;
        const s = i === 0 ? p.sL : p.sR;
        const w = p.w;
        const h = Math.max(1.6, (p.h - talk * 3) * openness + 2.4 * p.flat);
        e.g.setAttribute("transform", `translate(${((side * p.gap) / 2).toFixed(2)} ${p.ey.toFixed(2)}) scale(${s.toFixed(3)})`);
        // The clip is a unit larger than the eye so lids and cheeks also cover its
        // anti-aliased rim (ink on the ink oval beyond it), leaving no hairline.
        for (const [el, pad] of [
          [e.white, 0],
          [e.clip, 1],
        ] as const) {
          el.setAttribute("x", (-w / 2 - pad).toFixed(2));
          el.setAttribute("y", (-h / 2 - pad).toFixed(2));
          el.setAttribute("width", (w + 2 * pad).toFixed(2));
          el.setAttribute("height", (h + 2 * pad).toFixed(2));
          el.setAttribute("rx", (Math.min(w, h) / 2 + pad).toFixed(2));
        }
        e.white.setAttribute("opacity", (1 - p.dim * 0.5).toFixed(3));
        // Lid: ink over the top of the eye, slanted from the outer to the inner corner.
        const lo = (i === 0 ? p.loL : p.loR) * h;
        const li = (i === 0 ? p.liL : p.liR) * h;
        const ox = side * (w / 2 + 2); // outer corner: away from the other eye
        const ix = -side * (w / 2 + 2);
        const top = -h / 2 - 2;
        e.lid.setAttribute("d", `M${ox},${top} L${ix},${top} L${ix},${(-h / 2 + li).toFixed(2)} L${ox},${(-h / 2 + lo).toFixed(2)} Z`);
        // Happy cheeks rise from below until only a curved band is left: the eye becomes a ^.
        e.cheek.setAttribute("cy", lerp(h * 1.25, h * 0.3, p.happy).toFixed(2));
        e.cheek.setAttribute("rx", (w * 0.62).toFixed(2));
        e.cheek.setAttribute("ry", (h * 0.62).toFixed(2));
      }

      raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("pointermove", onMove);
      kick.current = null;
    };
  }, [bubbles]);

  const thoughtKey = activity ?? (mood === "asking" || mood === "sleepy" ? mood : null);
  const thinkingNow = bubbles && !speechOn && (mood === "thinking" || mood === "working" || mood === "asking" || mood === "sleepy") && !!thoughtKey;

  return (
    <span className={`bara-bot ${props.className ?? ""}`} style={{ width: size, height: size }} data-mood={mood} data-activity={activity ?? ""}>
      <svg ref={svg} viewBox="-60 -60 120 120" width={size} height={size} aria-label={`Assistant is ${activity ?? mood}`} role="img">
        <g className="bb-rig">
          <rect className="bb-oval" x={-OVAL_W / 2} y={-OVAL_H / 2} width={OVAL_W} height={OVAL_H} rx={OVAL_H / 2} />
          <g className="bb-face">
            {[0, 1].map((i) => (
              <g key={i} className={`bb-eye${i}`}>
                <clipPath id={`${uid}-eye${i}`} className={`bb-clip${i}`}>
                  <rect />
                </clipPath>
                <rect className="bb-white" />
                {/* Lids and cheeks only ever cover the eye itself. */}
                <g clipPath={`url(#${uid}-eye${i})`}>
                  <path className="bb-lid" />
                  <ellipse className="bb-cheek" cx="0" />
                </g>
              </g>
            ))}
          </g>
        </g>
      </svg>
      {bubbles && <ThoughtBubble on={thinkingNow} icons={thoughtKey ? THOUGHTS[thoughtKey] : []} />}
      {bubbles && <SpeechBubble on={speechOn} text={typed} />}
    </span>
  );
}

/** A thought cloud: two trailing puffs, then tiny icons that pop in one at a time. */
function ThoughtBubble(props: { on: boolean; icons: ThoughtIcon[] }) {
  const [k, setK] = useState(0);
  useEffect(() => {
    if (!props.on) return;
    const id = window.setInterval(() => setK((v) => v + 1), 1100);
    return () => window.clearInterval(id);
  }, [props.on]);
  const icon = props.icons.length ? props.icons[k % props.icons.length] : null;
  const next = props.icons.length ? props.icons[(k + 1) % props.icons.length] : null;
  return (
    <span className={`bb-thought ${props.on ? "on" : ""}`} aria-hidden="true">
      <span className="bb-puff p1" />
      <span className="bb-puff p2" />
      <span className="bb-cloud">
        {icon && (
          <span key={`${k}a`} className="bb-thing">
            <ThoughtGlyph icon={icon} />
          </span>
        )}
        {next && (
          <span key={`${k}b`} className="bb-thing small">
            <ThoughtGlyph icon={next} />
          </span>
        )}
      </span>
    </span>
  );
}

/** A speech bubble with a tail, text typed in as the bot says it. */
function SpeechBubble(props: { on: boolean; text: string }) {
  return (
    <span className={`bb-speech ${props.on && props.text ? "on" : ""}`} role="status" aria-live="polite">
      {props.text}
    </span>
  );
}
