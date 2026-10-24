// The director: turns the build's event stream into beats the agent acts out.
// Pure functions, so they are unit tested and AgentStage only plays what this
// module decides.
//
//   beatsFor  one event -> zero or more beats (where to fly, what to do, what to say)
//   enqueue   adds beats to the queue and trims it, so the bot stays close behind the build

import type { Build, BuildPart, CheckResult, Subject } from "../spec/types";
import type { AgentAction, AgentTarget, Beat } from "./agent";

interface EventLike {
  type: string;
  raw?: string;
}

interface Envelope {
  seq?: number;
  payload?: Record<string, unknown>;
}

function envelope(e: EventLike): Envelope {
  try {
    const env = JSON.parse(e.raw ?? "{}") as Envelope | null;
    return env && typeof env === "object" ? env : {};
  } catch {
    return {};
  }
}

/** Minimum time on each action. Long enough to read the chip, short enough to keep up. */
export const DWELL_MS: Record<AgentAction, number> = {
  look: 600,
  scan: 1200,
  pick: 800,
  drop: 700,
  trace: 1200,
  type: 1400,
  check: 600,
  cheer: 1800,
};

/** What each build stage is called when the server sends no label, and which panel follows it. */
const STAGES: Record<string, { label: string; open?: Beat["open"] }> = {
  classify: { label: "Reading your request" },
  reuse: { label: "Looking for a design", open: { rightTab: "build" } },
  compose: { label: "Choosing parts", open: { rightTab: "build" } },
  place: { label: "Placing parts", open: { rightTab: "design" } },
  enclose: { label: "Shaping the case", open: { rightTab: "design" } },
  board: { label: "Routing the board", open: { rightTab: "code", codeTab: "board" } },
  firmware: { label: "Writing firmware", open: { rightTab: "code", codeTab: "firmware" } },
  render: { label: "Setting up the scene" },
};

/** Labels live on a small chip: under 32 characters. */
const LABEL_MAX = 31;
const clip = (s: string, max = LABEL_MAX) => (s.length > max ? s.slice(0, max - 1).trimEnd() + "…" : s);

const dom = (key: string): AgentTarget => ({ kind: "dom", key });
const part = (id: string): AgentTarget => ({ kind: "part", id });

function beat(id: string, target: AgentTarget, action: AgentAction, label: string, extra?: Partial<Beat>): Beat {
  return { id, target, action, label: clip(label), dwellMs: DWELL_MS[action], ...extra };
}

const str = (v: unknown): string | null => (typeof v === "string" && v ? v : null);

/** What a part is called on screen: its instance label, else its catalog name. */
function nameOf(p: Pick<BuildPart, "label" | "card"> | undefined): string | null {
  return str(p?.label) ?? str(p?.card?.display_name);
}

/** The first instance a list of subjects points at, if any. */
const instanceOf = (subjects: Subject[] | undefined) => subjects?.find((s) => s.instance_id)?.instance_id ?? null;

/** Beats for one incoming event. build is the build after this event was reduced (may be null). */
export function beatsFor(e: EventLike, build: Build | null): Beat[] {
  const env = envelope(e);
  const p = env.payload ?? {};
  // seq is unique per build stream; fall back to an id from the payload.
  const tag = (fallback?: string | null) => `${e.type}:${env.seq ?? fallback ?? "0"}`;

  switch (e.type) {
    case "spec.ready":
      return [beat(tag(), dom("prompt"), "scan", "Reading your request")];

    case "stage.started": {
      const stage = str(p.stage) ?? "unknown";
      const known = STAGES[stage];
      const label = str(p.label) ?? known?.label ?? "Working on it";
      return [beat(tag(stage), dom(`stage:${stage}`), "look", label, known?.open ? { open: known.open } : undefined)];
    }

    case "reuse.decided": {
      const design = p.design as { name?: string } | null | undefined;
      const label = p.design_id
        ? design?.name
          ? `Starting from ${design.name}`
          : "Starting from an open design"
        : "Designing from scratch";
      return [beat(tag(), dom("viewport"), "scan", label)];
    }

    case "candidates.ready": {
      const survivors = (p.survivors as unknown[] | undefined) ?? [];
      // survivors is a short list; count_after is how many really made it through the filters.
      const n = typeof p.count_after === "number" ? p.count_after : survivors.length;
      const label = n === 0 ? "Nothing fits here" : n === 1 ? "One option left" : `Comparing ${n} options`;
      return [beat(tag(str(p.slot_id)), dom("tab:build"), "scan", label)];
    }

    case "decision.made": {
      const d = p.decision as { decision_id?: string; slot_id?: string; chosen_part_id?: string | null } | undefined;
      if (!d?.decision_id) return [];
      // The decision lands before its parts do, so the part may not be on the build yet.
      const chosen = d.chosen_part_id ? build?.parts.find((x) => x.part_id === d.chosen_part_id) : undefined;
      const slot = build?.slots.find((s) => s.slot_id === d.slot_id);
      const name = str(chosen?.card?.display_name);
      const label = name ? `Chose ${name}` : slot?.label ? `Picking the ${slot.label}` : "Making a choice";
      return [beat(tag(d.decision_id), dom(`decision:${d.decision_id}`), "pick", label)];
    }

    case "part.added": {
      const bp = p.part as BuildPart | undefined;
      if (!bp?.instance_id) return [];
      return [beat(tag(bp.instance_id), part(bp.instance_id), "drop", `Placing ${nameOf(bp) ?? "a part"}`)];
    }

    case "placement.updated":
      return [beat(tag(), dom("viewport"), "scan", "Arranging parts")];

    case "connection.added": {
      const c = p.connection as { connection_id?: string; from?: { instance_id?: string }; to?: { instance_id?: string } } | undefined;
      const from = c?.from?.instance_id;
      if (!from) return [];
      const to = c?.to?.instance_id;
      // Short names on both ends so the arrow fits on the chip.
      const short = (id: string | undefined) => clip(nameOf(build?.parts.find((x) => x.instance_id === id)) ?? id ?? "?", 10);
      return [
        beat(tag(c?.connection_id), part(from), "trace", `Wiring ${short(from)} → ${short(to)}`, {
          open: { rightTab: "code", codeTab: "connections" },
        }),
      ];
    }

    case "enclosure.updated":
      return [beat(tag(), dom("viewport"), "scan", "Shaping the case")];

    case "board.updated":
      return [beat(tag(), dom("viewport"), "trace", "Routing the board", { open: { rightTab: "code", codeTab: "board" } })];

    case "firmware.progress":
    case "firmware.ready":
      return [beat(tag(), dom("codetab:firmware"), "type", "Writing firmware")];

    case "check.result": {
      const results = (p.results as CheckResult[] | undefined) ?? [];
      // At most two per event: failures first, then whatever else is worth a tick.
      const picked = [...results.filter((r) => r.status === "fail"), ...results.filter((r) => r.status !== "fail")].slice(0, 2);
      return picked.map((r, i) => {
        const inst = instanceOf(r.subjects);
        const bad = r.status === "fail";
        const label = str(r.message) ?? (bad ? "Check failed" : "Check passed");
        return beat(`${tag(r.check_key)}:${i}`, inst ? part(inst) : dom(`check:${r.check_key}`), "check", label, bad ? { bad } : undefined);
      });
    }

    case "warning": {
      const w = p.warning as { warning_id?: string; message?: string; subjects?: Subject[] } | undefined;
      const inst = instanceOf(w?.subjects);
      return [beat(tag(w?.warning_id), inst ? part(inst) : dom("viewport"), "look", str(w?.message) ?? "Heads up", { bad: true })];
    }

    case "build.done":
      return [beat(tag(), dom("viewport"), "cheer", "Done")];

    case "build.failed":
      return [beat(tag(), dom("viewport"), "look", "That didn't work", { bad: true })];

    default:
      return [];
  }
}

/** Beats the queue may lose when it runs long: glances first, then real work. Never cheers or problems. */
function dropRank(b: Beat): number {
  if (b.bad || b.action === "cheer") return Infinity;
  return b.action === "look" || b.action === "scan" ? 0 : 1;
}

const sameTarget = (a: AgentTarget, b: AgentTarget) =>
  a.kind === b.kind && (a.kind === "part" ? a.id === (b as typeof a).id : a.key === (b as typeof a).key);

/** Append incoming beats to the queue, keeping it short so the bot never lags far behind the build. */
export function enqueue(queue: Beat[], incoming: Beat[], max = 6): Beat[] {
  let q = [...queue];
  for (const b of incoming) {
    if (q.some((x) => x.id === b.id)) continue;
    // A part landing again (re-added after an edit) replaces the older drop on it.
    if (b.action === "drop") q = q.filter((x) => !(x.action === "drop" && sameTarget(x.target, b.target)));
    // Back-to-back scans of the same thing are one scan: keep the newest.
    const last = q[q.length - 1];
    if (b.action === "scan" && last?.action === "scan" && sameTarget(last.target, b.target)) q.pop();
    q.push(b);
  }
  while (q.length > max) {
    // Oldest beat of the cheapest rank goes first.
    let victim = -1;
    for (let i = 0; i < q.length; i++) {
      if (dropRank(q[i]) === Infinity) continue;
      if (victim < 0 || dropRank(q[i]) < dropRank(q[victim])) victim = i;
    }
    if (victim < 0) break;
    q.splice(victim, 1);
  }
  return q;
}
