// Whole-build progress and time left, from the stage rows alone.
import { STAGE_IDS } from "../spec/types";
import type { StageView } from "./view";

/** Share of a typical live build each stage takes; the board (routing, DRC) dominates. */
const WEIGHT: Record<string, number> = {
  classify: 0.05,
  reuse: 0.02,
  compose: 0.25,
  place: 0.08,
  enclose: 0.1,
  board: 0.35,
  firmware: 0.05,
  render: 0.1,
};
/** A typical live build end to end (measured suite builds run 5 to 17 minutes). */
export const TYPICAL_MS = 7.5 * 60_000;

export interface Progress {
  fraction: number;
  /** Estimated ms left, null once nothing is running. */
  leftMs: number | null;
}

export function buildProgress(stages: Record<string, StageView>, startAt: number | null, now: number): Progress {
  let done = 0;
  let active = 0;
  for (const id of STAGE_IDS) {
    const s = stages[id];
    const w = WEIGHT[id] ?? 0;
    if (!s) continue;
    if (s.status === "ok" || s.status === "skipped" || s.status === "degraded") done += w;
    else if (s.status === "active" || s.status === "needs_input") {
      // a stage that reports its own fraction is trusted; otherwise time inside it counts,
      // capped so a slow stage never reads as finished
      const inStage = s.startedAt !== undefined ? now - s.startedAt : 0;
      const guess = s.fraction ?? inStage / (w * TYPICAL_MS);
      active += w * Math.min(0.9, Math.max(0, guess));
    }
  }
  const fraction = Math.min(0.99, done + active);
  if (startAt === null) return { fraction, leftMs: null };
  const elapsed = Math.max(0, now - startAt);
  // early on the typical build is the better guess; later the build's own pace is
  const leftMs = fraction < 0.15 ? Math.max(60_000, TYPICAL_MS - elapsed) : (elapsed * (1 - fraction)) / fraction;
  return { fraction, leftMs };
}

export function fmtLeft(ms: number): string {
  if (ms < 60_000) return "under a minute left";
  const m = Math.round(ms / 60_000);
  return `about ${m} min left`;
}

export function fmtDuration(ms: number): string {
  const s = Math.round(ms / 1000);
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`;
}
