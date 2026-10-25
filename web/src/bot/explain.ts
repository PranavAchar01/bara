// Why is this part here? Hovering a part (in the viewport or the parts list)
// makes the bot point at it and say why it was picked. This file turns the
// build into those words; Explainer.tsx plays them. Pure, so it is tested
// against the frozen fixtures.
import type { Build, BuildPart, Decision } from "../spec/types";
import type { ViewState } from "../state/view";

export interface PartExplanation {
  /** One line the bot says, at most 60 chars. */
  short: string;
  /** 2 to 4 short facts for the card. */
  long: string[];
}

export const SHORT_MAX = 60;

type View = Pick<ViewState, "candidates" | "reuse">;

/** "Corne (crkbd)" -> "Corne". */
function shortDesignName(name: string): string {
  return name.replace(/\s*\(.*\)\s*$/, "").trim() || name;
}

function clip(s: string, max: number): string {
  if (s.length <= max) return s;
  return s.slice(0, max - 1).trimEnd() + "…";
}

function plural(noun: string): string {
  if (/s$/.test(noun)) return noun;
  if (/[^aeiou]y$/.test(noun)) return noun.slice(0, -1) + "ies";
  return noun + "s";
}

function sentence(s: string): string {
  const t = s.trim();
  if (!t) return t;
  return /[.!?]$/.test(t) ? t : t + ".";
}

function decisionFor(build: Build, part: BuildPart): Decision | null {
  if (!part.slot_id) return null;
  const ds = (build.decisions ?? []).filter((d) => d.slot_id === part.slot_id);
  if (ds.length === 0) return null;
  // A decision that chose another part (since swapped out) says nothing about this one.
  for (let i = ds.length - 1; i >= 0; i--) if (ds[i].chosen_part_id === part.part_id) return ds[i];
  return null;
}

/** Name a part the way the parts list does: its label, or its card name. */
export function partName(part: BuildPart): string {
  return part.label || part.card.display_name || part.instance_id;
}

/** "Picked X: a, b" with tags dropped from the end until it fits. */
function withTags(head: string, tags: string[]): string {
  const t = tags.filter(Boolean);
  while (t.length > 0) {
    const s = `${head}: ${t.join(", ")}`;
    if (s.length <= SHORT_MAX) return s;
    t.pop();
  }
  return clip(head, SHORT_MAX);
}

/** "Runs on battery" -> "runs on battery"; "BLE" and "Pro Micro footprint" stay. */
function lowerFirst(s: string): string {
  if (/^[A-Z][a-z]*(\s+[a-z0-9]|$)/.test(s)) return s[0].toLowerCase() + s.slice(1);
  return s;
}

const FILTER_RANK: Record<string, number> = { requirement: 0, compatibility: 1 };

/** Who this part is wired to, and over what: "OLED left (I2C 0x3C)". */
function wiring(build: Build, part: BuildPart): string[] {
  const byId = new Map(build.parts.map((p) => [p.instance_id, p]));
  const out: string[] = [];
  const seen = new Set<string>();
  for (const c of build.connections) {
    let other: string | null = null;
    if (c.from.instance_id === part.instance_id) other = c.to.instance_id;
    else if (c.to.instance_id === part.instance_id) other = c.from.instance_id;
    if (!other || other === part.instance_id || seen.has(other)) continue;
    seen.add(other);
    const op = byId.get(other);
    const name = op ? partName(op) : other;
    const how = c.label || c.type.replace(/_/g, " ");
    out.push(how ? `${name} (${how})` : name);
  }
  return out;
}

function placementLine(build: Build, part: BuildPart): string | null {
  const bits: string[] = [];
  const side = part.side;
  if (side === "left" || side === "right") bits.push(`On the ${side} half`);
  else if (side === "center") bits.push("In the middle");
  const pl = part.placement;
  if (pl.mode === "layout") {
    const layout = build.layouts?.find((l) => l.layout_id === pl.layout_id);
    const n = layout?.keys.length ?? part.quantity;
    if (n > 1) bits.push(`one per key, ${n} keys`);
  } else if (part.quantity > 1) {
    bits.push(`${part.quantity} of them`);
  }
  const src = pl.source;
  if (pl.locked || src === "user") bits.push("where you put it");
  else if (src === "design") bits.push("where the design puts it");
  else if (src === "solver") bits.push("placed by the solver");
  if (bits.length === 0) return null;
  const s = bits.join(", ");
  return sentence(s[0].toUpperCase() + s.slice(1));
}

/**
 * Why this part was picked, from its slot's decision, the candidates that
 * were compared, the open design it came from, what it is wired to and where
 * it sits. Null when the instance is not in the build.
 */
export function explainPart(build: Build | null, view: View, instanceId: string): PartExplanation | null {
  if (!build) return null;
  const part = build.parts.find((p) => p.instance_id === instanceId);
  if (!part) return null;

  const name = part.card.display_name || partName(part);
  const dec = decisionFor(build, part);
  const reuse = view.reuse;
  const design = reuse?.design?.name ?? null;
  const designShort = design ? shortDesignName(design) : null;
  const fromDesign = dec?.method === "design" || part.origin === "design";
  const rounds = part.slot_id ? (view.candidates[part.slot_id] ?? []) : [];
  const last = rounds.length > 0 ? rounds[rounds.length - 1] : null;
  const slot = build.slots.find((s) => s.slot_id === part.slot_id);
  const slotNoun = plural((slot?.label ?? "option").toLowerCase());

  // ---- short line ----
  let short: string;
  if (fromDesign && designShort) {
    short =
      build.tier === "exact"
        ? `${name}, straight from the ${designShort}`
        : `Kept ${name} from the ${designShort}`;
    if (short.length > SHORT_MAX) short = `From the ${designShort} design`;
  } else if (dec?.method === "user" || (!dec && part.origin === "user")) {
    short = clip(`You picked ${name}`, SHORT_MAX);
  } else if (dec?.method === "only_survivor") {
    short = clip(`${name}, the only one that fit`, SHORT_MAX);
  } else if (dec && dec.method !== "none") {
    // The most telling filter (what you asked for first), then the design it fits.
    const best = [...(last?.filters ?? [])].sort(
      (a, b) => (FILTER_RANK[a.reason] ?? 2) - (FILTER_RANK[b.reason] ?? 2),
    )[0];
    const tags: string[] = [];
    if (best) tags.push(lowerFirst(best.label ?? String(best.value)));
    if (designShort && !/^fits\b/i.test(tags[0] ?? "")) tags.push(`fits the ${designShort}`);
    short = withTags(`Picked ${name}`, tags);
  } else {
    const fn = part.card.primary_function?.split(".").pop();
    short = clip(fn ? `${name}, the ${fn.replace(/_/g, " ")}` : name, SHORT_MAX);
  }

  // ---- long facts, most telling first ----
  const long: string[] = [];
  const reason = dec?.reason?.trim();
  const reuseLine =
    fromDesign && design
      ? sentence(
          `From the open ${design} design` +
            (reuse?.design?.licence_spdx ? ` (${reuse.design.licence_spdx})` : "") +
            (build.tier === "compose" ? ", kept as the skeleton" : ""),
        )
      : null;
  if (reuseLine) long.push(reuseLine);
  // Skip "From the Corne design." when the reuse line already says it.
  if (reason && !(reuseLine && designShort && reason.includes(designShort) && reason.length < 40)) {
    long.push(sentence(reason));
  }
  if (last && !fromDesign) {
    const others = last.survivors.filter((c) => c.card.part_id !== part.part_id);
    const mine = last.survivors.find((c) => c.card.part_id === part.part_id);
    let s = `Narrowed ${last.count_before} ${slotNoun} to ${last.count_after}`;
    const runner = others[0];
    if (runner) {
      s += `; runner-up ${runner.card.display_name}`;
      if (mine?.score != null && runner.score != null) s += ` (${runner.score.toFixed(2)} vs ${mine.score.toFixed(2)})`;
    }
    long.push(sentence(s));
  } else if (dec && !fromDesign && dec.survivors && dec.survivors > 1) {
    long.push(`Chosen from ${dec.survivors} that fit.`);
  }
  const wires = wiring(build, part);
  if (wires.length > 0) {
    const shown = wires.slice(0, 3).join(", ");
    long.push(sentence(`Wired to ${shown}${wires.length > 3 ? ` and ${wires.length - 3} more` : ""}`));
  }
  const place = placementLine(build, part);
  if (place) long.push(place);
  if (long.length < 2 && part.card.summary) long.push(sentence(part.card.summary));

  return { short, long: long.slice(0, 4) };
}
