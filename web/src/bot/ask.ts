// "Ask the bot" about one part (AskBot.tsx). Pure: text in, an intent out, then
// the intent plus the build data resolve to edit ops or an answer. The UI sends
// the ops through applyEdit and has the stage bot act it out.
import type { Build, BuildPart, EditOp, KeySpec, PartCard } from "../spec/types";
import { fmtValue } from "../ui/format";

export type SwapWant = "smaller" | "bigger" | "cheaper" | "lighter" | "any";
export type Topic = "why" | "what" | "specs" | "connections" | "options";

export type Intent =
  | { kind: "swap"; want: SwapWant; name: string | null }
  | { kind: "move"; delta: [number, number, number] }
  | { kind: "rotate"; deg: number }
  | { kind: "color"; hex: string; name: string; material: string | null; target: "part" | "case" }
  | { kind: "remove" }
  | { kind: "question"; topic: Topic }
  | { kind: "unknown" };

/** A swap option: an alternative from the REST endpoint or a survivor from candidates.ready. */
export interface SwapOption {
  card: PartCard;
  compatible?: boolean;
  score?: number | null;
}

export type Outcome =
  | { kind: "edit"; ops: EditOp[]; label: string; short: string; reply: string }
  | { kind: "answer"; say: string; reply: string };

export const FALLBACK = "I can swap, move, rotate, recolour or remove this part, or tell you why it was picked.";

/** Named colours, matching the ColorPicker swatches where there is one. */
export const COLORS: Record<string, string> = {
  red: "#C2362F",
  blue: "#2F55D4",
  green: "#2E7D4F",
  yellow: "#E3C23A",
  gold: "#D9A043",
  orange: "#E07A2E",
  purple: "#6B4FA8",
  violet: "#6B4FA8",
  pink: "#E07BA8",
  black: "#202326",
  white: "#F2F2EE",
  grey: "#9E9E9E",
  gray: "#9E9E9E",
  silver: "#C0C3C6",
  brown: "#7A5232",
  teal: "#2A8C8C",
  cyan: "#3BB6D6",
  navy: "#22305E",
  beige: "#D8CBB0",
};
const MATERIALS = ["plastic", "metal", "rubber", "wood", "glass", "fabric"];

const POLITE = /^(please\s+|can you\s+|could you\s+|would you\s+|will you\s+|i want( you)? to\s+|i'd like( you)? to\s+|let's\s+|lets\s+|go ahead and\s+)+/;
const QUESTION_START = /^(why|what|which|how|is|are|does|do|did|where|who|tell me|explain|describe)\b/;

/** Read what the user typed into an intent. */
export function parseAsk(raw: string): Intent {
  const text = raw.trim().toLowerCase().replace(/\s+/g, " ");
  if (!text) return { kind: "unknown" };
  const cmd = text.replace(POLITE, "").replace(/[.!]+$/, "");

  if (QUESTION_START.test(cmd)) return { kind: "question", topic: topicOf(cmd) };
  const color = parseColor(cmd);
  if (color) return color;
  if (/\b(remove|delete|get rid of|take (it|this|that) out|drop (it|this|that))\b/.test(cmd)) return { kind: "remove" };
  const rotate = parseRotate(cmd);
  if (rotate) return rotate;
  const move = parseMove(cmd);
  if (move) return move;
  const swap = parseSwap(cmd);
  if (swap) return swap;

  if (text.endsWith("?")) return { kind: "question", topic: topicOf(cmd) };
  return { kind: "unknown" };
}

function topicOf(t: string): Topic {
  if (/\b(connect|connected|wired|wiring|pins?|hooked|attached|talks? to)\b/.test(t)) return "connections";
  if (/\b(alternatives?|options?|instead|else|other)\b/.test(t)) return "options";
  if (/\b(why|chose|choose|chosen|pick|picked|reason)\b/.test(t)) return "why";
  if (/\b(specs?|size|big|dimensions?|weigh|weight|capacity|voltage|current|power|how much|how many|rating)\b/.test(t)) return "specs";
  return "what";
}

function parseColor(t: string): Intent | null {
  const hex = t.match(/#([0-9a-f]{6}|[0-9a-f]{3})\b/);
  const word = Object.keys(COLORS).find((c) => new RegExp(`\\b${c}\\b`).test(t));
  if (!hex && !word) return null;
  // A colour word alone ("red battery?") is not an instruction; a verb or "colour" makes it one.
  if (!hex && !/\b(make|paint|colou?r|recolou?r|turn|change|set|dye|tint|in)\b/.test(t)) return null;
  let h = hex ? `#${hex[1]}` : COLORS[word as string];
  if (h.length === 4) h = `#${h[1]}${h[1]}${h[2]}${h[2]}${h[3]}${h[3]}`;
  const material = MATERIALS.find((m) => t.includes(m)) ?? (/\bmetallic\b/.test(t) ? "metal" : null);
  return {
    kind: "color",
    hex: h.toUpperCase(),
    name: word ?? h.toUpperCase(),
    material,
    target: /\b(case|enclosure|housing|shell|box)\b/.test(t) ? "case" : "part",
  };
}

function parseRotate(t: string): Intent | null {
  if (!/\b(rotate|spin|flip|turn)\b/.test(t)) return null;
  // "turn it red" is handled by parseColor; "turn" alone needs a direction or angle.
  const n = t.match(/(-?\d+(?:\.\d+)?)\s*(?:°|deg|degrees?)?/);
  let deg = n ? Number(n[1]) : /\bflip\b|\baround\b/.test(t) ? 180 : 90;
  if (/\b(counter|anti)[- ]?clockwise\b|\bccw\b|\bleft\b/.test(t)) deg = Math.abs(deg);
  else if (/\bclockwise\b|\bcw\b|\bright\b/.test(t)) deg = -Math.abs(deg);
  if (/\bturn\b/.test(t) && !n && !/\b(around|left|right|clockwise|counter|anti|over)\b/.test(t)) return null;
  return { kind: "rotate", deg };
}

/** Build-space axes: +X right, +Y back (away from the viewer), +Z up. */
const DIRS: Record<string, [number, number, number]> = {
  left: [-1, 0, 0],
  right: [1, 0, 0],
  up: [0, 0, 1],
  higher: [0, 0, 1],
  raise: [0, 0, 1],
  down: [0, 0, -1],
  lower: [0, 0, -1],
  forward: [0, -1, 0],
  forwards: [0, -1, 0],
  front: [0, -1, 0],
  closer: [0, -1, 0],
  back: [0, 1, 0],
  backward: [0, 1, 0],
  backwards: [0, 1, 0],
  away: [0, 1, 0],
};

function toMm(n: number, unit: string | undefined): number {
  if (!unit) return n;
  if (unit.startsWith("c")) return n * 10;
  if (unit.startsWith("in") || unit === '"') return n * 25.4;
  return n;
}

function parseMove(t: string): Intent | null {
  const verb = /\b(move|shift|nudge|slide|push|pull|bring|put|raise|lower)\b/.test(t);
  const dirRe = /\b(left|right|up|higher|raise|down|lower|forwards?|front|closer|backwards?|back|away)\b/g;
  if (!verb && !/\d\s*(mm|cm|in)\b/.test(t)) return null;
  const delta: [number, number, number] = [0, 0, 0];
  let found = false;
  // Each clause carries its own amount: "5mm left and 2 mm up".
  for (const clause of t.split(/\band\b|,|\bthen\b/)) {
    const dirs = [...clause.matchAll(dirRe)].map((m) => m[1]);
    if (!dirs.length) continue;
    const num = clause.match(/(\d+(?:\.\d+)?)\s*(mm|millimet\w*|cm|centimet\w*|inch(?:es)?|in\b|")?/);
    const mm = num ? toMm(Number(num[1]), num[2]) : /\b(nudge|bit|little|slightly)\b/.test(t) ? 2 : 5;
    for (const d of dirs) {
      const v = DIRS[d];
      for (let i = 0; i < 3; i++) delta[i] += v[i] * mm;
    }
    found = true;
  }
  if (!found) return null;
  return { kind: "move", delta: delta.map((v) => Math.round(v * 100) / 100) as [number, number, number] };
}

const WANTS: [SwapWant, RegExp][] = [
  ["smaller", /\b(smaller|tinier|compact|more compact|thinner|shorter|slimmer|less capacity|lower capacity)\b/],
  ["bigger", /\b(bigger|larger|longer lasting|more capacity|higher capacity|more power|stronger)\b/],
  ["cheaper", /\b(cheaper|less expensive|budget|cheap|lower cost)\b/],
  ["lighter", /\b(lighter|less heavy)\b/],
];

function parseSwap(t: string): Intent | null {
  const verb = /\b(swap|replace|change|switch|use|try|exchange|pick|choose|give me|find|get)\b/.test(t);
  const want = WANTS.find(([, re]) => re.test(t))?.[0] ?? null;
  if (!verb && !want) return null;
  const m = t.match(/\b(?:for|to|with|into|use|try)\s+(?:an?\s+|the\s+|something\s+)?(.+)$/);
  let name: string | null = m ? m[1] : null;
  if (name) {
    for (const [, re] of WANTS) name = name.replace(re, " ");
    name = name.replace(/\b(one|part|this|it|that|instead|another|different|something|else|please|option)\b/g, " ").replace(/\s+/g, " ").trim();
    if (name.length < 2) name = null;
  }
  return { kind: "swap", want: want ?? "any", name };
}

// ---- Resolving ----

export interface AskContext {
  build: Build;
  instance: BuildPart;
  /** Alternatives for the instance's slot, current part included or not. */
  options: SwapOption[];
}

function clip(s: string, n = 60): string {
  const one = s.replace(/\s+/g, " ").trim();
  if (one.length <= n) return one;
  const cut = one.slice(0, n - 1);
  const sp = cut.lastIndexOf(" ");
  return `${(sp > n * 0.6 ? cut.slice(0, sp) : cut).replace(/[,;:.]$/, "")}…`;
}

function firstSentence(s: string): string {
  const m = s.match(/^.+?[.!?](\s|$)/);
  return (m ? m[0] : s).trim();
}

function fmtMm(v: number): string {
  return `${Math.round(Math.abs(v) * 10) / 10} mm`;
}

const SIZE_RE = /size|dim|length|width|height|thick|diameter|volume|footprint|capacity|mah|wh\b/i;
const PRICE_RE = /price|cost|usd|\$/i;
const WEIGHT_RE = /weight|mass/i;

/** A number from a spec value: "1200 mAh" -> 1200, "30 x 20 x 5" -> 3000 (volume). */
export function specNumber(v: KeySpec["value"]): number | null {
  if (typeof v === "number") return v;
  if (typeof v !== "string") return null;
  const nums = (v.match(/-?\d+(?:\.\d+)?/g) ?? []).map(Number);
  if (!nums.length) return null;
  if (/\d\s*[x×]\s*\d/i.test(v)) return nums.reduce((a, b) => a * b, 1);
  return nums[0];
}

function metric(card: PartCard, re: RegExp, label?: string): { label: string; value: number } | null {
  for (const k of card.key_specs ?? []) {
    if (label ? k.label !== label : !re.test(`${k.label} ${k.unit ?? ""}`)) continue;
    const n = specNumber(k.value);
    if (n !== null) return { label: k.label, value: n };
  }
  return null;
}

function nameScore(card: PartCard, name: string): number {
  const hay = `${card.display_name} ${card.part_id} ${card.primary_function ?? ""}`.toLowerCase();
  if (hay.includes(name)) return 100;
  return name.split(/[\s-]+/).filter((w) => w.length > 1 && hay.includes(w)).length;
}

/** Choose the alternative that best matches what was asked; null with a reason when none does. */
export function pickSwap(current: PartCard, options: SwapOption[], want: SwapWant, name: string | null): { card: PartCard; why: string } | { card: null; why: string } {
  const seen = new Set<string>();
  let pool = options.filter((o) => {
    if (o.card.part_id === current.part_id || o.compatible === false || seen.has(o.card.part_id)) return false;
    seen.add(o.card.part_id);
    return true;
  });
  if (!pool.length) return { card: null, why: "There are no compatible alternatives for this slot." };
  if (name) {
    const scored = pool.map((o) => ({ o, s: nameScore(o.card, name) })).sort((a, b) => b.s - a.s);
    if (want === "any") {
      if (scored[0].s > 0) return { card: scored[0].o.card, why: `it matches "${name}"` };
      return { card: null, why: `None of the ${pool.length} alternatives match "${name}".` };
    }
    // "a smaller battery": the name narrows the pool, the comparison picks.
    const named = scored.filter((x) => x.s > 0).map((x) => x.o);
    if (named.length) pool = named;
  }
  if (want === "any") {
    const best = [...pool].sort((a, b) => (b.score ?? 0) - (a.score ?? 0))[0];
    return { card: best.card, why: "it is the next best fit" };
  }
  const re = want === "cheaper" ? PRICE_RE : want === "lighter" ? WEIGHT_RE : SIZE_RE;
  const cur = metric(current, re);
  if (!cur) return { card: null, why: `I can't tell how ${want} compares: ${current.display_name} has no ${want === "cheaper" ? "price" : want === "lighter" ? "weight" : "size"} spec.` };
  const lower = want !== "bigger";
  const ranked = pool
    .map((o) => ({ o, m: metric(o.card, re, cur.label) }))
    .filter((x): x is { o: SwapOption; m: { label: string; value: number } } => !!x.m && (lower ? x.m.value < cur.value : x.m.value > cur.value))
    // Smallest step that satisfies the ask, so "smaller" is not "tiniest".
    .sort((a, b) => Math.abs(a.m.value - cur.value) - Math.abs(b.m.value - cur.value));
  if (!ranked.length) return { card: null, why: `${current.display_name} is already the ${want === "bigger" ? "biggest" : `${want.replace(/er$/, "")}est`} option here.` };
  const top = ranked[0];
  return { card: top.o.card, why: `${cur.label} ${fmtValue(cur.value)} to ${fmtValue(top.m.value)}` };
}

function decisionFor(build: Build, inst: BuildPart) {
  return [...(build.decisions ?? [])].reverse().find((d) => d.slot_id === inst.slot_id && d.chosen_part_id === inst.part_id) ?? null;
}

function nameOf(build: Build, id: string): string {
  const p = build.parts.find((x) => x.instance_id === id);
  return p ? (p.label ?? p.card.display_name) : id;
}

/** Turn an intent into edit ops or an answer for this part. */
export function resolveAsk(intent: Intent, ctx: AskContext): Outcome {
  const { build, instance: inst } = ctx;
  const name = inst.card.display_name;
  switch (intent.kind) {
    case "remove":
      return {
        kind: "edit",
        ops: [{ op: "remove_part", instance_id: inst.instance_id }],
        label: `Remove ${name}`,
        short: `removing ${name}`,
        reply: `Removing ${name}.`,
      };
    case "move": {
      const [x, y, z] = intent.delta;
      const parts = [x && `${fmtMm(x)} ${x < 0 ? "left" : "right"}`, y && `${fmtMm(y)} ${y < 0 ? "forward" : "back"}`, z && `${fmtMm(z)} ${z < 0 ? "down" : "up"}`].filter(Boolean);
      if (!parts.length) return { kind: "answer", say: "That move cancels out", reply: "Those directions cancel out, so nothing moves." };
      const where = parts.join(", ");
      return {
        kind: "edit",
        ops: [{ op: "move", instance_id: inst.instance_id, position_mm: intent.delta, mode: "delta", lock: true }],
        label: `Move ${name} ${where}`,
        short: `moving it ${where}`,
        reply: `Moving ${name} ${where}.`,
      };
    }
    case "rotate": {
      const dir = intent.deg < 0 ? "clockwise" : "counter-clockwise";
      const amt = `${Math.abs(intent.deg)}°`;
      return {
        kind: "edit",
        ops: [{ op: "move", instance_id: inst.instance_id, rotation_deg: [0, 0, intent.deg], mode: "delta", lock: true }],
        label: `Rotate ${name} ${amt}`,
        short: `turning it ${amt}`,
        reply: `Rotating ${name} ${amt} ${dir}.`,
      };
    }
    case "color": {
      const enc = intent.target === "case" ? build.enclosures.find((e) => e.kind !== "none") : undefined;
      if (intent.target === "case" && !enc) return { kind: "answer", say: "There's no case to paint", reply: "This build has no generated case to recolour." };
      const color = { hex: intent.hex, material: intent.material ?? (enc ? enc.color?.material : inst.color?.material) ?? "plastic" };
      const what = enc ? "the case" : name;
      return {
        kind: "edit",
        ops: [enc ? { op: "recolor", enclosure_id: enc.enclosure_id, color } : { op: "recolor", instance_id: inst.instance_id, color }],
        label: `Recolor ${what} ${intent.name}`,
        short: `painting ${enc ? "the case" : "it"} ${intent.name}`,
        reply: `Making ${what} ${intent.name} (${intent.hex}, ${color.material}).`,
      };
    }
    case "swap": {
      if (!inst.slot_id) return { kind: "answer", say: "This one can't be swapped", reply: `${name} isn't in a slot, so there is nothing to swap it with.` };
      const pick = pickSwap(inst.card, ctx.options, intent.want, intent.name);
      if (!pick.card) return { kind: "answer", say: clip(pick.why), reply: `${pick.why} Open Swap (S) to see every option.` };
      const siblings = build.parts.filter((p) => p.slot_id === inst.slot_id && p.part_id === inst.part_id);
      const targets = siblings.length ? siblings : [inst];
      const to = pick.card.display_name;
      return {
        kind: "edit",
        ops: targets.map((t) => ({ op: "swap_part", instance_id: t.instance_id, part_id: pick.card.part_id })),
        label: `Swap to ${to}`,
        short: `swapping in ${to}`,
        reply: `Swapping ${name} for ${to}${targets.length > 1 ? ` (all ${targets.length} in this slot)` : ""}: ${pick.why}.`,
      };
    }
    case "question":
      return answer(intent.topic, ctx);
    case "unknown":
      return { kind: "answer", say: "I can swap, move, rotate, recolour or remove", reply: FALLBACK };
  }
}

function answer(topic: Topic, ctx: AskContext): Outcome {
  const { build, instance: inst } = ctx;
  const card = inst.card;
  const name = card.display_name;
  if (topic === "why") {
    const d = decisionFor(build, inst);
    if (d?.reason) {
      const n = d.survivors ? ` (${d.survivors} candidate${d.survivors === 1 ? "" : "s"} left)` : "";
      return { kind: "answer", say: clip(firstSentence(d.reason)), reply: `${d.reason}${n}` };
    }
    if (inst.origin === "design" || inst.placement.source === "design")
      return { kind: "answer", say: "It came with the design", reply: `${name} is part of the design this build started from.` };
    return { kind: "answer", say: "No recorded reason for this one", reply: `I don't have a recorded decision for ${name}.` };
  }
  if (topic === "connections") {
    const links = build.connections.filter((c) => c.from.instance_id === inst.instance_id || c.to.instance_id === inst.instance_id);
    if (!links.length) return { kind: "answer", say: "It isn't wired to anything", reply: `${name} has no connections yet.` };
    const others = links.map((c) => {
      const other = c.from.instance_id === inst.instance_id ? c.to.instance_id : c.from.instance_id;
      return `${nameOf(build, other)} (${c.label ?? c.type})`;
    });
    const uniq = [...new Set(links.map((c) => (c.from.instance_id === inst.instance_id ? c.to.instance_id : c.from.instance_id)))];
    return {
      kind: "answer",
      say: clip(uniq.length === 1 ? `Wired to ${nameOf(build, uniq[0])}` : `Wired to ${uniq.length} parts`),
      reply: `Connected to ${others.join(", ")}.`,
    };
  }
  if (topic === "specs") {
    const specs = (card.key_specs ?? []).map((k) => `${k.label} ${fmtValue(k.value, k.unit)}`);
    if (!specs.length) return { kind: "answer", say: "No key specs on file", reply: `The catalog has no key specs for ${name}.` };
    return { kind: "answer", say: clip(specs.slice(0, 2).join(", ")), reply: `${name}: ${specs.join(", ")}.` };
  }
  if (topic === "options") {
    const n = ctx.options.filter((o) => o.card.part_id !== card.part_id && o.compatible !== false).length;
    return n
      ? { kind: "answer", say: `${n} other option${n === 1 ? "" : "s"} fit here`, reply: `${n} compatible alternative${n === 1 ? "" : "s"}. Try "swap for a smaller one" or open Swap (S).` }
      : { kind: "answer", say: "Nothing else fits this slot", reply: "There are no compatible alternatives for this slot." };
  }
  const what = card.summary || [card.primary_function, card.kind].filter(Boolean).join(", ") || name;
  return { kind: "answer", say: clip(firstSentence(what)), reply: card.summary ? `${name}: ${card.summary}` : `${name} is a ${what}.` };
}
