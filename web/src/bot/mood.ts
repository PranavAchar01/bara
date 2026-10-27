// What the bot feels, from what the build is doing. Pure functions over the
// store and the event stream, so they are unit tested and the character only
// animates what this module decides.
//
//   mood      the lasting state: how the face rests (idle, listening, asking, sad...)
//   activity  what it is doing right now, acted out with gaze and body (one per stage)
//   emote     a one-shot reaction to a single event (a nod per part, a wince per failed check)

import type { ConnStatus } from "../net/connection";

export type Mood =
  | "idle"
  | "listening"
  | "thinking"
  | "working"
  | "asking"
  | "happy"
  | "worried"
  | "sad"
  | "sleepy"
  | "offline"
  | "connecting";

export type Activity = "read" | "search" | "pick" | "arrange" | "sculpt" | "route" | "type" | "admire";

export type Emote = "nod" | "hop" | "wince" | "surprise" | "delight" | "shake" | "yawn" | "pop";

/** One build stage, acted out. Order follows SPEC 2.1. */
export const STAGE_ACTIVITY: Record<string, Activity> = {
  classify: "read",
  reuse: "search",
  compose: "pick",
  place: "arrange",
  enclose: "sculpt",
  board: "route",
  firmware: "type",
  render: "admire",
};

export interface BotInputs {
  conn: ConnStatus;
  buildStatus?: string | null;
  /** The stage currently active, if any. */
  stage?: string | null;
  /** The user is typing in the prompt. */
  typing: boolean;
  /** Milliseconds since anything happened (input, event). */
  quietMs: number;
  /** Milliseconds since the build finished, when it did. */
  sinceDoneMs?: number | null;
}

/** Mood and activity for the current moment. */
export function moodOf(i: BotInputs): { mood: Mood; activity: Activity | null } {
  if (i.conn === "offline") return { mood: "offline", activity: null };
  if (i.conn === "connecting" || i.conn === "reconnecting") return { mood: "connecting", activity: null };
  if (i.typing) return { mood: "listening", activity: null };
  const status = i.buildStatus ?? null;
  if (status === "awaiting_input") return { mood: "asking", activity: null };
  if (status === "running") {
    const activity = (i.stage && STAGE_ACTIVITY[i.stage]) || "read";
    // Reading and searching are thinking; the rest is hands-on work.
    return { mood: activity === "read" || activity === "search" ? "thinking" : "working", activity };
  }
  if (status === "failed" || status === "cancelled") return { mood: status === "failed" ? "sad" : "idle", activity: null };
  if (status === "done" && i.sinceDoneMs != null && i.sinceDoneMs < 4000) return { mood: "happy", activity: "admire" };
  if (i.quietMs > 45000) return { mood: "sleepy", activity: null };
  return { mood: "idle", activity: null };
}

interface EventLike {
  type: string;
  raw?: string;
}

function payload(e: EventLike): Record<string, unknown> {
  try {
    const env = JSON.parse(e.raw ?? "{}") as { payload?: Record<string, unknown> };
    return env.payload ?? {};
  } catch {
    return {};
  }
}

/** One-shot reaction to an event, or null when it does not deserve one. */
export function emoteFor(e: EventLike): Emote | null {
  switch (e.type) {
    case "part.added":
      return "pop";
    case "decision.made":
    case "board.updated":
    case "enclosure.updated":
      return "nod";
    case "reuse.decided":
    case "scene.ready":
      return "surprise";
    case "build.done":
      return "delight";
    case "build.failed":
      return "shake";
    case "decision.reverted":
    case "warning":
    case "warning.added":
      return "wince";
    case "check.result": {
      const results = (payload(e).results as { status?: string }[] | undefined) ?? [];
      return results.some((r) => r.status === "fail") ? "wince" : null;
    }
    default:
      return null;
  }
}

const SPEECH_MAX = 60;
const short = (s: string) => (s.length > SPEECH_MAX ? s.slice(0, SPEECH_MAX - 1).trimEnd() + "…" : s);

/** What Bara says as each stage starts: a person talking, not a status line. */
const STAGE_LINES: Record<string, string> = {
  classify: "Ooh, okay. Let me picture this.",
  reuse: "Let's see what's out there already.",
  compose: "Shopping for parts!",
  place: "Now, where does everything go?",
  enclose: "Time to give it a home.",
  board: "Wiring it all up.",
  firmware: "Teaching it what to do.",
  render: "Almost there. Making it pretty.",
};

/** A part, in a line: what it is to you, under ten words. First match wins. */
const PART_LINES: [RegExp, string[]][] = [
  [/knob/i, ["Ooh, a knob. That's your volume.", "A knob. Twist away."]],
  [/encoder|potentiometer|\bpot\b|dial/i, ["Ooh, a dial. Something to twist.", "A dial. Your fingers will love this."]],
  [/keycap/i, ["Keycaps! The part you actually touch.", "Caps on. Looking like a keyboard now."]],
  [/switch/i, ["Switches! That's the clicky bit.", "Here come the clicks."]],
  [/trackball/i, ["A trackball. Rolling, rolling.", "Trackball! Thumb's gonna love it."]],
  [/joystick|thumbstick|stick/i, ["A stick. Game on.", "Joystick! This one's for fun."]],
  [/oled|display|screen|lcd/i, ["A little screen. Now it can talk back.", "A screen! Something to look at."]],
  [/battery|lipo|cell/i, ["A battery. No cable needed.", "Power, packed in."]],
  [/controller|mcu|microcontroller|pico|\bboard\b/i, ["There's the brain.", "The brain goes in."]],
  [/usb|connector|jack|port/i, ["A port, so it can plug in.", "Plug goes here."]],
  [/buzzer|speaker|piezo/i, ["A buzzer. It can beep at you now.", "Beep beep. Found a buzzer."]],
  [/led|light/i, ["A light. Little bit of glow.", "Ooh, it lights up."]],
  [/button/i, ["A button. Press it, it'll know.", "Buttons! Something to press."]],
  [/diode/i, ["Diodes. Tiny traffic cops.", "Diodes keep the keys honest."]],
  [/standoff|screw|spacer/i, ["Standoffs. Keeps it sturdy.", "Little legs for the board."]],
  [/sensor/i, ["A sensor. It can feel things now.", "A sensor! Now it notices."]],
  [/motor|fan/i, ["A motor. It moves!", "Something that spins. Fun."]],
];

function pick(options: string[], key: string): string {
  let h = 0;
  for (let i = 0; i < key.length; i++) h = (h * 31 + key.charCodeAt(i)) | 0;
  return options[Math.abs(h) % options.length];
}

/** What Bara says when a part goes in: a reaction to what the part is for. */
export function partLine(name: string, seed = ""): string {
  for (const [re, lines] of PART_LINES) if (re.test(name)) return pick(lines, name + seed);
  const plain = name.length > 28 ? "this one" : name.toLowerCase();
  return pick([`Ooh, ${plain}. Nice.`, `Grabbed ${plain}.`], name + seed);
}

/** One line the bot says about an event (spoken and shown as a popup): short, warm, under ten words. */
export function speechFor(e: EventLike): string | null {
  const p = payload(e);
  switch (e.type) {
    case "stage.started": {
      const id = typeof p.stage === "string" ? p.stage : null;
      if (id && STAGE_LINES[id]) return STAGE_LINES[id];
      const label = typeof p.label === "string" ? p.label : null;
      return label ? short(label) : null;
    }
    case "part.added": {
      const part = p.part as { label?: string; instance_id?: string; card?: { display_name?: string } } | undefined;
      const name = part?.label ?? part?.card?.display_name;
      return name ? partLine(name, part?.instance_id ?? "") : null;
    }
    case "reuse.decided":
      return "Found a design to build on. Nice.";
    case "clarify.request":
      return typeof p.question === "string" ? short(p.question) : "Quick question for you";
    case "build.done":
      return "There it is. All done!";
    case "build.failed":
      return "Oof. That one didn't work.";
    case "check.result": {
      const results = (p.results as { status?: string; message?: string }[] | undefined) ?? [];
      return results.some((r) => r.status === "fail") ? "Hmm, something's off. Looking." : null;
    }
    default:
      return null;
  }
}

/** Tiny things the bot thinks about while doing each activity (thought bubble). */
export type ThoughtIcon = "lines" | "lens" | "switch" | "chip" | "grid" | "box" | "trace" | "code" | "spark" | "question" | "heart" | "zzz";

export const THOUGHTS: Record<Activity | "asking" | "sleepy", ThoughtIcon[]> = {
  read: ["lines", "question", "lines"],
  search: ["lens", "box", "lens"],
  pick: ["switch", "chip", "switch"],
  arrange: ["grid", "switch", "grid"],
  sculpt: ["box", "grid", "box"],
  route: ["trace", "chip", "trace"],
  type: ["code", "chip", "code"],
  admire: ["spark", "heart", "spark"],
  asking: ["question", "question", "lines"],
  sleepy: ["zzz", "zzz", "zzz"],
};
