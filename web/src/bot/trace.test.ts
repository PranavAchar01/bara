import { describe, expect, it } from "vitest";
import type { Build, Candidate, Decision, PartCard, Slot } from "../spec/types";
import type { LogEntry } from "../state/store";
import { emptyView, type ViewState } from "../state/view";
import { buildTrace, fmtDur, nowLine } from "./trace";

const label = (id: string) => ({ classify: "Understand", compose: "Choose parts", place: "Place", board: "Board" })[id] ?? id;

function card(id: string, name: string): PartCard {
  return { part_id: id, display_name: name } as PartCard;
}

function slot(id: string, order: number, extra: Partial<Slot> = {}): Slot {
  return { slot_id: id, label: id.toUpperCase(), function_id: "f", criticality: "critical", order, state: "decided", ...extra } as Slot;
}

function build(extra: Partial<Build> = {}): Build {
  return {
    build_id: "b1",
    prompt: "a macro pad",
    status: "running",
    revision: 1,
    tier: "compose",
    slots: [],
    parts: [],
    connections: [],
    enclosures: [],
    boards: [],
    checks: [],
    warnings: [],
    last_seq: 0,
    ...extra,
  } as Build;
}

function view(stages: Record<string, Partial<ViewState["stages"][string]>>, extra: Partial<ViewState> = {}): ViewState {
  const v = emptyView();
  for (const [id, st] of Object.entries(stages)) v.stages[id] = { id, status: "pending", ...st };
  return { ...v, ...extra };
}

function entry(type: string, payload: unknown, t: number, buildId = "b1"): LogEntry {
  return { id: t, t, dir: "in", type, buildId, raw: JSON.stringify({ type, payload }) };
}

const candidates = (slot_id: string, before: number, after: number, survivors: Candidate[] = []) => ({
  slot_id,
  step: 1,
  filters: [{ facet: "voltage", op: "<=", value: 5, reason: "requirement" as const, count_before: before, count_after: after, label: "Voltage" }],
  count_before: before,
  count_after: after,
  survivors,
});

describe("fmtDur", () => {
  it("reads in ms, then seconds, then minutes", () => {
    expect(fmtDur(850)).toBe("850 ms");
    expect(fmtDur(4200)).toBe("4.2 s");
    expect(fmtDur(72_000)).toBe("72 s");
    expect(fmtDur(132_000)).toBe("2m 12s");
    expect(fmtDur(-1)).toBe("");
  });
});

describe("buildTrace", () => {
  it("is empty before any stage has started", () => {
    const t = buildTrace({ build: build(), view: emptyView(), log: [], label });
    expect(t.groups).toEqual([]);
    expect(t.final).toBeNull();
  });

  it("lists started stages in pipeline order, the working one live", () => {
    const t = buildTrace({
      build: build(),
      view: view({ compose: { status: "active" }, classify: { status: "ok", duration_ms: 40 } }),
      log: [],
      label,
    });
    expect(t.groups.map((g) => g.id)).toEqual(["classify", "compose"]);
    expect(t.groups.map((g) => g.live)).toEqual([false, true]);
    expect(t.groups[0].summary).toBe("Understand: 40 ms");
    // a working stage has no time to show yet
    expect(t.groups[1].summary).toBe("Choose parts");
  });

  it("turns slots into a search row with filter chips and a clickable decision", () => {
    const decision: Decision = {
      decision_id: "d1",
      slot_id: "sw",
      method: "model_pick",
      chosen_part_id: "p-switch",
      reason: "Lowest profile that fits the plate.",
      model: { model: "m1", latency_ms: 1200 },
    };
    const b = build({
      slots: [slot("sw", 1, { instance_ids: ["i1"] }), slot("mcu", 0)],
      decisions: [decision],
      parts: [{ instance_id: "i1", slot_id: "sw", part_id: "p-switch", card: card("p-switch", "Kailh Choc") }] as Build["parts"],
    });
    const v = view({ compose: { status: "ok", duration_ms: 72_000 } }, { candidates: { sw: [candidates("sw", 40, 3)] } });
    const t = buildTrace({ build: b, view: v, log: [], label });
    const rows = t.groups[0].rows;
    expect(rows.map((r) => r.id)).toEqual(["search:sw", "decision:d1"]);
    expect(rows[0].chips).toEqual([{ text: "Voltage", counts: "40 → 3", tone: "muted" }]);
    expect(rows[0].detail).toBe("40 candidates, 3 left");
    expect(rows[1].title).toBe("Chose Kailh Choc");
    expect(rows[1].meta).toBe("model pick · m1 1.2 s");
    expect(rows[1].target).toEqual({ instanceId: "i1" });
    expect(t.groups[0].summary).toBe("Choose parts: 1 part, 1 search narrowed, 72 s");
  });

  it("points a decision at the catalog part when nothing was placed yet", () => {
    const d: Decision = { decision_id: "d1", slot_id: "sw", method: "only_survivor", chosen_part_id: "p1", reason: "Only one left." };
    const b = build({ slots: [slot("sw", 0)], decisions: [d] });
    const t = buildTrace({ build: b, view: view({ compose: { status: "active" } }), log: [], label });
    expect(t.groups[0].rows[0].target).toEqual({ partId: "p1" });
    expect(t.groups[0].rows[0].title).toBe("Chose a part for SW");
  });

  it("marks a slot with no survivors as a failed search and a dead end", () => {
    const b = build({ slots: [slot("sw", 0, { state: "dead_end" })] });
    const v = view({ compose: { status: "failed" } }, { candidates: { sw: [candidates("sw", 12, 0)] } });
    const rows = buildTrace({ build: b, view: v, log: [], label }).groups[0].rows;
    expect(rows[0].tone).toBe("fail");
    expect(rows[0].chips?.[0].tone).toBe("fail");
    expect(rows[1]).toMatchObject({ id: "dead:sw", tone: "fail" });
  });

  it("puts failed checks under their stage, or the latest started stage", () => {
    const b = build({
      checks: [
        { check_key: "c1", rule_id: "clearance", status: "fail", severity: "error", message: "Switch too close", stage: "place" },
        { check_key: "c2", rule_id: "erc", status: "fail", severity: "warning", message: "Pin floating" },
        { check_key: "c3", rule_id: "ok", status: "pass", severity: "info", message: "fine", stage: "place" },
      ],
    });
    const v = view({ place: { status: "ok" }, board: { status: "active" } });
    const t = buildTrace({ build: b, view: v, log: [], label });
    const [place, board] = t.groups;
    expect(place.rows.map((r) => r.id)).toEqual(["check:c1"]);
    expect(place.rows[0].tone).toBe("fail");
    expect(place.summary).toBe("Place: 1 check failed");
    expect(board.rows.map((r) => [r.id, r.tone])).toEqual([["check:c2", "warn"]]);
  });

  it("takes row times from the event log, relative to the build's first event", () => {
    const d: Decision = { decision_id: "d1", slot_id: "sw", method: "default", chosen_part_id: "p1", reason: "r" };
    const b = build({ slots: [slot("sw", 0)], decisions: [d] });
    const v = view({ compose: { status: "active" } }, { candidates: { sw: [candidates("sw", 5, 2)] } });
    const log = [
      entry("stage.started", { stage: "classify" }, 1000),
      entry("candidates.ready", { slot_id: "sw", step: 1 }, 2500),
      entry("decision.made", { decision: { decision_id: "d1" } }, 4000),
      entry("decision.made", { decision: { decision_id: "d1" } }, 9000), // a repeat does not move it
      entry("decision.made", { decision: { decision_id: "d1" } }, 500, "other"), // another build's event
    ];
    const rows = buildTrace({ build: b, view: v, log, label }).groups[0].rows;
    expect(rows[0].at).toBeCloseTo(1.5);
    expect(rows[1].at).toBeCloseTo(3);
  });

  it("copes with a truncated log entry", () => {
    const b = build({ slots: [slot("sw", 0)] });
    const v = view({ compose: { status: "active" } }, { candidates: { sw: [candidates("sw", 5, 2)] } });
    const log: LogEntry[] = [{ ...entry("candidates.ready", {}, 100), raw: '{"type":"candidates.ready","payload":{"slot' }];
    const rows = buildTrace({ build: b, view: v, log, label }).groups[0].rows;
    expect(rows[0].at).toBeUndefined();
  });

  it("ends with the done summary, and works for a build opened from the library", () => {
    const done = buildTrace({
      build: build({ status: "done" }),
      view: view({ compose: { status: "ok" } }, { done: { summary: { part_count: 19, instance_count: 19, connection_count: 24, warning_count: 1, checks: {} }, timings_ms: {}, total_ms: 5200 } }),
      log: [],
      label,
    });
    expect(done.final).toEqual({ text: "Done: 19 parts, 24 connections, 1 warning, 5.2 s", tone: "ok" });

    const opened = buildTrace({
      build: build({ status: "done", timings_ms: { classify: 400, compose: 1600 } }),
      view: view({ compose: { status: "ok", duration_ms: 1600 } }),
      log: [],
      label,
    });
    expect(opened.final).toEqual({ text: "Done: 0 parts, 2.0 s", tone: "ok" });
  });

  it("ends with the failure message", () => {
    const t = buildTrace({
      build: build({ status: "failed" }),
      view: view({ compose: { status: "failed" } }, { failure: { error: { code: "no_part", message: "No switch fits", retryable: false } } }),
      log: [],
      label,
    });
    expect(t.final).toEqual({ text: "Stopped: No switch fits", tone: "fail" });
    expect(t.groups[0].summary).toBe("Choose parts: failed");
  });
});

describe("nowLine", () => {
  it("is the newest step of the stage that is working", () => {
    const tr = buildTrace({
      build: build(),
      view: view({ classify: { status: "ok" }, compose: { status: "active" } }),
      log: [],
      label,
    });
    const now = nowLine(tr);
    expect(now?.live).toBe(true);
    expect(now?.stage).toBe("Choose parts");
  });
  it("says nothing before anything has started", () => {
    expect(nowLine({ groups: [], final: null })).toBeNull();
  });
  it("is the closing line once the build is over", () => {
    expect(nowLine({ groups: [], final: { text: "Done: 3 parts", tone: "ok" } })).toMatchObject({ stage: "", text: "Done: 3 parts", live: false });
  });
});
