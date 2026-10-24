import { describe, expect, it, vi } from "vitest";
import type { ServerEnvelope } from "../spec/types";
import type { LogEntry } from "../state/store";

vi.mock("../net/client", () => ({
  applyServerEnvelope: vi.fn(),
  getRest: vi.fn(),
  takeHeldDuringReplay: () => [],
}));

const { buildSchedule, eventsFromEnvelopes, eventsFromLog, FALLBACK_STEP_MS, MAX_GAP_MS } = await import("./replay");

function env(seq: number, type = "part.added", build_id: string | null = "b1", ts = "2026-01-01T00:00:00.000Z"): ServerEnvelope {
  return { spec_version: "1", type, seq, build_id, ts, payload: {} };
}

function entry(e: ServerEnvelope, t: number, extra: Partial<LogEntry> = {}): LogEntry {
  return { id: t, t, dir: "in", type: e.type, seq: e.seq, raw: JSON.stringify(e), ...extra };
}

describe("eventsFromLog", () => {
  it("keeps this build's events in seq order, once each, and skips the rest", () => {
    const log: LogEntry[] = [
      entry(env(2), 200),
      entry(env(1), 100),
      entry(env(2), 250), // duplicate seq
      entry(env(3, "part.added", "other"), 300),
      entry(env(0, "hello", null), 50),
      entry(env(4, "build.snapshot"), 400),
      entry(env(5), 500, { dir: "out" }),
      entry(env(6), 600, { note: "replay" }),
      { ...entry(env(7), 700), raw: '{"type":"part.added","seq":7...' }, // truncated raw
      entry(env(8, "build.done"), 800),
    ];
    const out = eventsFromLog(log, "b1");
    expect(out.map((e) => e.env.seq)).toEqual([1, 2, 8]);
    expect(out.map((e) => e.at)).toEqual([100, 200, 800]);
  });
});

describe("eventsFromEnvelopes", () => {
  it("times events by their ts", () => {
    const out = eventsFromEnvelopes([env(2, "x", "b1", "2026-01-01T00:00:01.000Z"), env(1, "x", "b1", "2026-01-01T00:00:00.000Z")], "b1");
    expect(out.map((e) => e.env.seq)).toEqual([1, 2]);
    expect(out[1].at - out[0].at).toBe(1000);
  });
});

describe("buildSchedule", () => {
  const timed = (ats: number[]) => ats.map((at, i) => ({ env: env(i + 1), at }));

  it("keeps the original relative timing at 1x", () => {
    expect(buildSchedule(timed([1000, 1100, 1400]), 1).map((s) => s.delay)).toEqual([0, 100, 400]);
  });

  it("divides by speed", () => {
    expect(buildSchedule(timed([0, 100, 400]), 2).map((s) => s.delay)).toEqual([0, 50, 200]);
    expect(buildSchedule(timed([0, 100, 400]), 0.5).map((s) => s.delay)).toEqual([0, 200, 800]);
  });

  it("caps long pauses before applying speed", () => {
    expect(buildSchedule(timed([0, 60_000, 60_100]), 1).map((s) => s.delay)).toEqual([0, MAX_GAP_MS, MAX_GAP_MS + 100]);
    expect(buildSchedule(timed([0, 60_000]), 4).map((s) => s.delay)).toEqual([0, MAX_GAP_MS / 4]);
  });

  it("treats backwards clocks as no gap", () => {
    expect(buildSchedule(timed([500, 100, 200]), 1).map((s) => s.delay)).toEqual([0, 0, 100]);
  });

  it("falls back to an even step when timing is missing", () => {
    expect(buildSchedule(timed([NaN, NaN, NaN]), 1).map((s) => s.delay)).toEqual([0, FALLBACK_STEP_MS, 2 * FALLBACK_STEP_MS]);
  });

  it("handles empty and single inputs", () => {
    expect(buildSchedule([], 1)).toEqual([]);
    expect(buildSchedule(timed([5]), 1).map((s) => s.delay)).toEqual([0]);
  });
});
