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

/** The same wording for the same thing (a line said again plays from memory), but not the same
 *  wording for everything, so it sounds like someone talking rather than a status readout. */
function pick(options: string[], seed: string): string {
  let h = 0;
  for (const c of seed) h = (h * 31 + c.charCodeAt(0)) | 0;
  return options[Math.abs(h) % options.length];
}

/** The tone a line is said in: the voice is upbeat for a hello, curious while building, delighted
 *  when it works and kind when it doesn't. */
export type SpeechMood = "greeting" | "progress" | "question" | "success" | "failure" | "reply";

export function speechMoodFor(type: string): SpeechMood {
  if (type === "build.done") return "success";
  if (type === "build.failed" || type === "check.result") return "failure";
  if (type === "clarify.request") return "question";
  return "progress";
}

/** One line the bot says about an event (SPEC UI: under 60 characters), or null. Written the way a
 *  person at the bench would say it: contractions, a little reaction first. */
export function speechFor(e: EventLike): string | null {
  const p = payload(e);
  switch (e.type) {
    case "stage.started": {
      const label = typeof p.label === "string" ? p.label : null;
      if (!label) return null;
      const said = label.charAt(0).toLowerCase() + label.slice(1);
      return short(pick([label, `Okay, ${said}`, `Alright, ${said}`], label));
    }
    case "part.added": {
      const part = p.part as { label?: string; card?: { display_name?: string } } | undefined;
      const name = part?.label ?? part?.card?.display_name;
      return name ? short(pick([`Got ${name}`, `Ooh, got ${name}`, `Okay, nice. ${name}`], name)) : null;
    }
    case "reuse.decided":
      return "Ooh, found an open design to start from";
    case "clarify.request":
      return typeof p.question === "string" ? short(p.question) : "Quick question for you";
    case "build.done": {
      const s = p.summary as { instance_count?: number } | undefined;
      return s?.instance_count ? short(`Done! ${s.instance_count} parts, all placed`) : "Done! Take a look";
    }
    case "build.failed": {
      const err = p.error as { message?: string } | undefined;
      return short(err?.message ? `Hmm. ${err.message}` : "Ah, that one didn't work");
    }
    case "check.result": {
      const results = (p.results as { status?: string; message?: string }[] | undefined) ?? [];
      const bad = results.find((r) => r.status === "fail");
      return bad?.message ? short(`Uh oh, ${bad.message}`) : null;
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
