// The candidate fly-by: while the build chooses parts, a few option cards fan
// out next to the bot, flash through as if it is comparing, the losers drop
// away and the chosen one pops and flies into its parts list row. This file is
// the pure half (which cards, what they say, how long each phase takes), so
// CandidateFlyby.tsx only animates what it decides.

import type { Candidate, Decision, KeySpec, PartKind } from "../spec/types";

/** At most this many cards per fly-by. */
export const MAX_CARDS = 6;
/** How long the chosen card waits for its part.added before it just fades. */
export const PART_WAIT_MS = 2000;

export interface FlyCard {
  partId: string;
  name: string;
  kind: string;
  /** One or two key specs, already formatted ("nRF52840 · BLE 5"). */
  specs: string;
  /** 0..1, or null when the server sent no score. */
  score: number | null;
}

export interface FlyItem {
  /** Unique per fly-by (decision id, else slot and seq). */
  key: string;
  slotId: string;
  cards: FlyCard[];
  /** Index of the chosen card in cards, or -1 when none of them won. */
  winner: number;
  winnerPartId: string | null;
  /** How many options really made it through the filters (cards is a short list). */
  countAfter: number;
}

export interface Envelope {
  type?: string;
  seq?: number;
  payload?: Record<string, unknown>;
}

export function envelopeOf(raw: string | undefined): Envelope {
  try {
    const env = JSON.parse(raw ?? "{}") as Envelope | null;
    return env && typeof env === "object" ? env : {};
  } catch {
    return {};
  }
}

const clip = (s: string, max: number) => (s.length > max ? s.slice(0, max - 1).trimEnd() + "…" : s);

const KINDS: Record<string, string> = {
  module: "Module",
  component: "Part",
  pcb: "PCB",
  mechanical: "Mech",
  fastener: "Fastener",
  cable: "Cable",
};

export function kindLabel(kind: PartKind | undefined): string {
  return (kind && KINDS[kind]) ?? "";
}

/** A key spec as it fits on a small card: the value and unit ("3.3 V"); a true flag shows its label. */
export function formatSpec(k: KeySpec): string | null {
  if (typeof k.value === "boolean") return k.value ? k.label : null;
  const v = typeof k.value === "number" ? String(Math.round(k.value * 100) / 100) : k.value.trim();
  if (!v) return null;
  return k.unit ? `${v} ${k.unit}` : v;
}

export function specLine(specs: KeySpec[] | undefined, max = 2): string {
  const out: string[] = [];
  for (const k of specs ?? []) {
    const s = formatSpec(k);
    if (s && !out.includes(s)) out.push(s);
    if (out.length >= max) break;
  }
  return clip(out.join(" · "), 30);
}

export function cardFor(c: Candidate): FlyCard {
  const score = typeof c.score === "number" && Number.isFinite(c.score) ? Math.min(1, Math.max(0, c.score)) : null;
  return {
    partId: c.card.part_id,
    name: clip(c.card.display_name || c.card.part_id, 26),
    kind: kindLabel(c.card.kind),
    specs: specLine(c.card.key_specs),
    score,
  };
}

/**
 * Which survivors to show: the server's order, no duplicates, at most cap.
 * The winner always makes it in: if it sits past the cap it takes the last seat.
 */
export function pickCards(survivors: Candidate[], winnerId: string | null | undefined, cap = MAX_CARDS): Candidate[] {
  const seen = new Set<string>();
  const uniq = survivors.filter((c) => {
    const id = c?.card?.part_id;
    if (!id || seen.has(id)) return false;
    seen.add(id);
    return true;
  });
  const top = uniq.slice(0, Math.max(1, cap));
  if (winnerId && !top.some((c) => c.card.part_id === winnerId)) {
    const w = uniq.find((c) => c.card.part_id === winnerId);
    if (w) top[top.length - 1] = w;
  }
  return top;
}

/** One fly-by from a slot's candidates and the decision that settled it; null when there is nothing to show. */
export function flybyFrom(cand: { slot_id?: unknown; count_after?: unknown; survivors?: unknown }, d: Decision, seq?: number): FlyItem | null {
  const survivors = Array.isArray(cand.survivors) ? (cand.survivors as Candidate[]) : [];
  const picked = pickCards(survivors, d.chosen_part_id);
  if (!picked.length) return null;
  const cards = picked.map(cardFor);
  const winner = d.chosen_part_id ? cards.findIndex((c) => c.partId === d.chosen_part_id) : -1;
  return {
    key: d.decision_id || `${d.slot_id}:${seq ?? 0}`,
    slotId: d.slot_id,
    cards,
    winner,
    winnerPartId: winner >= 0 ? d.chosen_part_id : null,
    countAfter: typeof cand.count_after === "number" ? cand.count_after : survivors.length,
  };
}

/**
 * Follows the event stream: remembers each slot's candidates until its decision
 * lands, then hands back a fly-by. Also remembers where each chosen part landed
 * (part_id -> first instance_id), so the winner knows which row to fly into.
 */
export class FlybyTracker {
  private candidates = new Map<string, Record<string, unknown>>();
  private placed = new Map<string, string>();

  feed(type: string, payload: Record<string, unknown> | undefined, seq?: number): FlyItem | null {
    const p = payload ?? {};
    switch (type) {
      case "build.snapshot": {
        // A fresh (or resumed) build: start over from the parts it already has.
        this.candidates.clear();
        this.placed.clear();
        const parts = (p.build as { parts?: { instance_id?: string; part_id?: string }[] } | undefined)?.parts ?? [];
        for (const x of parts) if (x.part_id && x.instance_id && !this.placed.has(x.part_id)) this.placed.set(x.part_id, x.instance_id);
        return null;
      }
      case "build.done":
      case "build.failed":
        // Leftovers would pair with the next build's decisions.
        this.candidates.clear();
        return null;
      case "candidates.ready":
        if (typeof p.slot_id === "string") this.candidates.set(p.slot_id, p);
        return null;
      case "decision.made": {
        const d = p.decision as Decision | undefined;
        if (!d?.slot_id) return null;
        const cand = this.candidates.get(d.slot_id);
        // Decisions without candidates (a reused design) were never compared.
        if (!cand) return null;
        this.candidates.delete(d.slot_id);
        return flybyFrom(cand, d, seq);
      }
      case "part.added": {
        const part = p.part as { instance_id?: string; part_id?: string } | undefined;
        if (part?.part_id && part.instance_id && !this.placed.has(part.part_id)) this.placed.set(part.part_id, part.instance_id);
        return null;
      }
      case "part.removed": {
        const id = p.instance_id;
        for (const [k, v] of this.placed) if (v === id) this.placed.delete(k);
        return null;
      }
      default:
        return null;
    }
  }

  /** Where a chosen part landed, once its part.added has arrived. */
  instanceFor(partId: string | null): string | null {
    return (partId && this.placed.get(partId)) ?? null;
  }
}

export type FlyMode = "full" | "quick" | "winner" | "static";

export interface FlyPlan {
  mode: FlyMode;
  /** Cards fan out from the bot. */
  fanMs: number;
  /** Highlight flashes through the cards. */
  shuffleMs: number;
  /** Losers drop, the winner pops and gets its tick. */
  settleMs: number;
  /** Winner shrinks into its row (or everything fades). */
  exitMs: number;
}

/**
 * Timing for the next fly-by. waiting is how many more are queued behind it:
 * the queue compresses so the cards keep pace with the build, and past three
 * waiting it shows only the chosen card. Reduced motion shows them still.
 */
export function planFor(item: Pick<FlyItem, "cards" | "winner">, waiting: number, reduced: boolean): FlyPlan {
  if (reduced) return { mode: "static", fanMs: 0, shuffleMs: 0, settleMs: waiting > 1 ? 700 : 1400, exitMs: 200 };
  const n = item.cards.length;
  if (waiting > 3 || n <= 1) return { mode: "winner", fanMs: 220, shuffleMs: 0, settleMs: waiting > 3 ? 420 : 620, exitMs: 380 };
  if (waiting >= 2) return { mode: "quick", fanMs: 260, shuffleMs: 300, settleMs: 380, exitMs: 380 };
  return { mode: "full", fanMs: 340, shuffleMs: Math.min(960, Math.max(480, n * 170)), settleMs: 560, exitMs: 450 };
}

/** The cards a plan shows: winner mode keeps only the chosen card (or the first one). */
export function cardsFor(item: FlyItem, mode: FlyMode): { cards: FlyCard[]; winner: number } {
  if (mode !== "winner") return { cards: item.cards, winner: item.winner };
  const w = item.winner >= 0 ? item.winner : 0;
  return { cards: [item.cards[w]], winner: item.winner >= 0 ? 0 : -1 };
}

/**
 * The order the highlight flashes through the cards: steps indices, never the
 * same card twice in a row, ending on the winner. Deterministic per seed.
 */
export function shuffleSequence(n: number, winner: number, steps: number, seed = 1): number[] {
  if (n <= 0 || steps <= 0) return [];
  const end = winner >= 0 && winner < n ? winner : n - 1;
  if (n === 1) return Array(steps).fill(0);
  let s = (seed * 2654435761) >>> 0;
  const rand = () => {
    s = (s ^ (s << 13)) >>> 0;
    s = (s ^ (s >>> 17)) >>> 0;
    s = (s ^ (s << 5)) >>> 0;
    return s / 4294967296;
  };
  const out: number[] = [];
  for (let i = 0; i < steps - 1; i++) {
    const prev = out[i - 1] ?? -1;
    // The step before last must not be the winner either, or the end would repeat.
    const avoid = i === steps - 2 ? end : -1;
    let k = Math.floor(rand() * n);
    for (let tries = 0; (k === prev || k === avoid) && tries < n * 2; tries++) k = (k + 1) % n;
    out.push(k);
  }
  out.push(end);
  return out;
}

/** A small stable number from a string, to seed the shuffle per slot. */
export function seedOf(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619);
  return (h >>> 0) || 1;
}
