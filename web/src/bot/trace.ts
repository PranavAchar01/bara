// The thinking trace, as data: one build's story told stage by stage, built only
// from what the store already holds (stages, slots, candidates, decisions,
// checks, the event log for timing). ThoughtTrace.tsx draws it; nothing here
// touches React or the DOM, so it is the part the tests pin down.
import { STAGE_IDS } from "../spec/types";
import type { Build, CheckResult, Decision, PartCard, Slot } from "../spec/types";
import type { LogEntry } from "../state/store";
import type { StageRowStatus, ViewState } from "../state/view";
import { known } from "../ui/format";

export type TraceKind = "step" | "search" | "decision" | "check" | "note";
export type TraceTone = "ok" | "fail" | "warn" | "accent" | "muted";

/** What a click on a row selects: an instance on the canvas, or a catalog part for the inspector. */
export interface TraceTarget {
  instanceId?: string;
  partId?: string;
}

export interface TraceChip {
  text: string;
  /** "before → after", empty when the filter did not report counts. */
  counts: string;
  tone: TraceTone;
}

export interface TraceRow {
  id: string;
  kind: TraceKind;
  title: string;
  detail?: string;
  meta?: string;
  tone: TraceTone;
  chips?: TraceChip[];
  target?: TraceTarget;
  /** Seconds since the build started, when the event log saw it. */
  at?: number;
}

export interface TraceGroup {
  id: string;
  label: string;
  status: StageRowStatus;
  /** The line a folded group shows: "Choose parts: 19 parts, 3 searches narrowed, 72 s". */
  summary: string;
  rows: TraceRow[];
  /** The stage still working: shown open and followed. */
  live: boolean;
}

export interface Trace {
  groups: TraceGroup[];
  /** The closing line once the build is done or has failed. */
  final: { text: string; tone: TraceTone } | null;
}

export interface TraceInput {
  build: Build | null;
  view: ViewState;
  log: LogEntry[];
  /** Stage id to vocab label. */
  label: (stageId: string) => string;
}

/** 850 ms, 4.2 s, 72 s, 2m 12s. */
export function fmtDur(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return "";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 10_000) return `${(ms / 1000).toFixed(1)} s`;
  const s = Math.round(ms / 1000);
  return s < 120 ? `${s} s` : `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`;
}

interface EventTimes {
  /** Client clock of the first event of this build. */
  t0: number | null;
  /** And of the last: a build opened from the library arrives all at once and has no times worth showing. */
  t1: number;
  decision: Map<string, number>;
  candidates: Map<string, number>;
  check: Map<string, number>;
}

function pluck(raw: string): { payload?: Record<string, unknown> } | null {
  try {
    return JSON.parse(raw) as { payload?: Record<string, unknown> };
  } catch {
    return null; // the log keeps a truncated copy of very large events
  }
}

/** First arrival time of the events the trace rows come from, from the event log. */
function eventTimes(log: LogEntry[], buildId: string | undefined): EventTimes {
  const out: EventTimes = { t0: null, t1: 0, decision: new Map(), candidates: new Map(), check: new Map() };
  for (const e of log) {
    if (e.dir !== "in" || e.unknown || !buildId || e.buildId !== buildId) continue;
    if (out.t0 === null) out.t0 = e.t;
    out.t1 = e.t;
    if (e.type !== "decision.made" && e.type !== "candidates.ready" && e.type !== "check.result") continue;
    const p = pluck(e.raw)?.payload;
    if (!p) continue;
    if (e.type === "decision.made") {
      const id = (p.decision as { decision_id?: string } | undefined)?.decision_id;
      if (id && !out.decision.has(id)) out.decision.set(id, e.t);
    } else if (e.type === "candidates.ready") {
      const key = `${String(p.slot_id)}:${String(p.step)}`;
      if (!out.candidates.has(key)) out.candidates.set(key, e.t);
    } else {
      for (const r of (p.results as { check_key?: string }[] | undefined) ?? []) {
        if (r.check_key && !out.check.has(r.check_key)) out.check.set(r.check_key, e.t);
      }
    }
  }
  return out;
}

function secsSince(times: EventTimes, t: number | undefined): number | undefined {
  return times.t0 === null || times.t1 - times.t0 < 1000 || t === undefined ? undefined : Math.max(0, (t - times.t0) / 1000);
}

function cardOf(build: Build, d: Decision, slot: Slot, survivors: PartCard[]): PartCard | undefined {
  const id = d.chosen_part_id ?? slot.chosen_part_id;
  return build.parts.find((p) => p.part_id === id)?.card ?? survivors.find((c) => c.part_id === id);
}

const METHOD_TEXT: Record<string, string> = {
  design: "from the design",
  only_survivor: "only one left",
  default: "default pick",
  model_pick: "model pick",
  solver: "solver",
  user: "your pick",
  none: "nothing fits",
};

function methodText(m: string): string {
  return METHOD_TEXT[m] ?? m.replace("_", " ");
}

function slotRows(build: Build, view: ViewState, times: EventTimes): TraceRow[] {
  const decisions = build.decisions ?? [];
  const rows: TraceRow[] = [];
  const slots = [...build.slots].sort((a, b) => (a.order ?? 999) - (b.order ?? 999));
  for (const slot of slots) {
    const steps = view.candidates[slot.slot_id] ?? [];
    const last = steps[steps.length - 1];
    const decision = [...decisions].reverse().find((d) => d.slot_id === slot.slot_id);
    const state = known(slot.state, ["pending", "narrowing", "decided", "none", "dead_end"] as const);
    const instanceId = slot.instance_ids?.[0] ?? build.parts.find((p) => p.slot_id === slot.slot_id)?.instance_id;
    const survivors = (last?.survivors ?? []).map((c) => c.card);
    const card = decision ? cardOf(build, decision, slot, survivors) : undefined;
    const target: TraceTarget | undefined = instanceId ? { instanceId } : decision?.chosen_part_id ? { partId: decision.chosen_part_id } : undefined;

    if (last) {
      const first = steps[0];
      const chips: TraceChip[] = last.filters.map((f) => ({
        text: f.label ?? f.facet,
        counts: f.count_before !== undefined && f.count_after !== undefined ? `${f.count_before} → ${f.count_after}` : "",
        tone: f.count_after === 0 ? "fail" : "muted",
      }));
      rows.push({
        id: `search:${slot.slot_id}`,
        kind: "search",
        title: `Searching ${slot.label}`,
        detail: `${first.count_before} candidates, ${last.count_after} left`,
        tone: last.count_after === 0 ? "fail" : "muted",
        chips,
        at: secsSince(times, times.candidates.get(`${slot.slot_id}:${last.step}`)),
      });
    }
    if (decision) {
      const m = decision.model;
      const bits = [methodText(decision.method)];
      if (m?.model) bits.push(`${m.model}${m.latency_ms !== undefined ? ` ${fmtDur(m.latency_ms)}` : ""}${m.cached ? " cached" : ""}${m.fallback ? " fallback" : ""}`);
      rows.push({
        id: `decision:${decision.decision_id}`,
        kind: "decision",
        title: card ? `Chose ${card.display_name}` : decision.chosen_part_id === null ? `Nothing chosen for ${slot.label}` : `Chose a part for ${slot.label}`,
        detail: decision.reason,
        meta: bits.join(" · "),
        tone: decision.chosen_part_id === null ? "warn" : "ok",
        target,
        at: secsSince(times, times.decision.get(decision.decision_id)),
      });
    } else if (state === "dead_end") {
      rows.push({ id: `dead:${slot.slot_id}`, kind: "decision", title: `No part fits ${slot.label}`, detail: "Every candidate failed a requirement.", tone: "fail" });
    }
  }
  return rows;
}

function checkRow(c: CheckResult, times: EventTimes): TraceRow {
  const hard = known(c.severity, ["info", "warning", "error", "critical"] as const);
  return {
    id: `check:${c.check_key}`,
    kind: "check",
    title: c.message,
    detail: c.fix_hint ?? undefined,
    meta: c.rule_id,
    tone: hard === "error" || hard === "critical" ? "fail" : "warn",
    at: secsSince(times, times.check.get(c.check_key)),
  };
}

function stageRows(id: string, build: Build | null, view: ViewState, times: EventTimes): TraceRow[] {
  const rows: TraceRow[] = [];
  const msg = view.stages[id]?.message;
  if (id === "classify" && build?.spec?.main_purpose) {
    rows.push({ id: "spec", kind: "step", title: "Understood the prompt", detail: build.spec.main_purpose, tone: "muted" });
  }
  if (id === "reuse" && view.reuse) {
    const r = view.reuse;
    const tier = known(r.tier, ["exact", "substitute", "compose", "unknown"] as const);
    rows.push({
      id: "reuse",
      kind: "note",
      title: r.design ? `Found ${r.design.name}` : tier === "compose" ? "No design to start from" : "Looked for a design",
      detail: r.reason,
      meta: r.considered.length ? `${r.considered.length} considered` : undefined,
      tone: "muted",
    });
  }
  if (id === "compose" && build) rows.push(...slotRows(build, view, times));
  if (id === "firmware" && view.firmwareProgress?.message) {
    rows.push({ id: "fw", kind: "note", title: view.firmwareProgress.message, tone: "muted" });
  }
  if (msg && !rows.some((r) => r.detail === msg)) rows.push({ id: `msg:${id}`, kind: "step", title: msg, tone: "muted" });
  return rows;
}

/** The checks that failed, by the stage that ran them (the last stage that started, when a check names none). */
function failedByStage(build: Build | null, view: ViewState): Map<string, CheckResult[]> {
  const out = new Map<string, CheckResult[]>();
  const started = STAGE_IDS.filter((id) => view.stages[id] && view.stages[id].status !== "pending");
  const fallback = started[started.length - 1];
  for (const c of build?.checks ?? []) {
    if (known(c.status, ["pass", "fail"] as const) !== "fail") continue;
    const stage = c.stage && (STAGE_IDS as readonly string[]).includes(c.stage) && started.includes(c.stage as (typeof STAGE_IDS)[number]) ? c.stage : fallback;
    if (!stage) continue;
    out.set(stage, [...(out.get(stage) ?? []), c]);
  }
  return out;
}

function summaryOf(label: string, g: { id: string; status: StageRowStatus; rows: TraceRow[]; ms?: number; parts: number }): string {
  const bits: string[] = [];
  if (g.id === "compose") {
    if (g.parts) bits.push(`${g.parts} part${g.parts === 1 ? "" : "s"}`);
    const searched = g.rows.filter((r) => r.kind === "search").length;
    if (searched) bits.push(`${searched} search${searched === 1 ? "" : "es"} narrowed`);
  }
  const bad = g.rows.filter((r) => r.kind === "check").length;
  if (bad) bits.push(`${bad} check${bad === 1 ? "" : "s"} failed`);
  else if (g.status === "failed") bits.push("failed");
  else if (g.status === "degraded") bits.push("partly done");
  else if (g.status === "skipped") bits.push("skipped");
  else if (g.status === "needs_input") bits.push("needs your answer");
  if (g.ms !== undefined && Math.round(g.ms) > 0) bits.push(fmtDur(g.ms));
  return bits.length ? `${label}: ${bits.join(", ")}` : label;
}

/** Turn the store's build data into the trace: one group per stage that has started, in pipeline order. */
export function buildTrace(input: TraceInput): Trace {
  const { build, view } = input;
  const times = eventTimes(input.log, build?.build_id);
  const failed = failedByStage(build, view);
  const groups: TraceGroup[] = [];
  for (const id of STAGE_IDS) {
    const st = view.stages[id];
    if (!st || st.status === "pending") continue;
    const rows = stageRows(id, build, view, times);
    for (const c of failed.get(id) ?? []) rows.push(checkRow(c, times));
    const live = st.status === "active";
    const ms = st.duration_ms ?? (build?.timings_ms ?? {})[id];
    const label = input.label(id);
    groups.push({
      id,
      label,
      status: st.status,
      rows,
      live,
      summary: summaryOf(label, { id, status: st.status, rows, ms: live ? undefined : ms, parts: build?.parts.length ?? 0 }),
    });
  }

  let final: Trace["final"] = null;
  const failure = view.failure?.error ?? (build?.status === "failed" ? build.error : null);
  if (failure) {
    final = { text: `Stopped: ${failure.message}`, tone: "fail" };
  } else if (view.done || build?.status === "done") {
    // A build opened from the library never saw build.done: count it from the build itself.
    const s = view.done?.summary;
    const timings = Object.values(build?.timings_ms ?? {});
    const total = view.done?.total_ms ?? view.doneMs ?? (timings.length ? timings.reduce((a, b) => a + b, 0) : null);
    const parts = s?.part_count ?? build?.parts.length ?? 0;
    const warnings = s?.warning_count ?? build?.warnings.length ?? 0;
    const wires = s?.connection_count ?? build?.connections.length ?? 0;
    const bits = [`${parts} parts`];
    if (wires) bits.push(`${wires} connection${wires === 1 ? "" : "s"}`);
    if (warnings) bits.push(`${warnings} warning${warnings === 1 ? "" : "s"}`);
    if (total !== null) bits.push(fmtDur(total));
    final = { text: `Done: ${bits.join(", ")}`, tone: "ok" };
  }
  return { groups, final };
}
