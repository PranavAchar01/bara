// View state that is not part of Build (SPEC 9, last paragraph): stage rows,
// candidate lists, the pending edit, firmware progress, failure details.
// Rebuilt from the same events as the Build.
import type {
  CheckResult,
  EditOp,
  ErrorObject,
  ServerEnvelope,
  ServerPayloads,
  Suggestion,
} from "../spec/types";
import { STAGE_IDS } from "../spec/types";

export type StageRowStatus = "pending" | "active" | "ok" | "skipped" | "degraded" | "failed" | "needs_input" | "unknown";

export interface StageView {
  id: string;
  status: StageRowStatus;
  label?: string;
  budget_ms?: number;
  /** Client clock (ms) when stage.started arrived. */
  startedAt?: number;
  duration_ms?: number;
  message?: string | null;
  fraction?: number | null;
}

export type EditPhase = "pending" | "applying" | "applied" | "rejected";
export interface EditView {
  msg_id: string;
  edit_id?: string | null;
  ops: EditOp[];
  phase: EditPhase;
  label?: string;
  error?: ErrorObject | null;
  failed_checks?: CheckResult[];
  suggestions?: Suggestion[];
  duration_ms?: number;
}

export interface ViewState {
  stages: Record<string, StageView>;
  candidates: Record<string, ServerPayloads["candidates.ready"][]>;
  reuse: ServerPayloads["reuse.decided"] | null;
  firmwareProgress: ServerPayloads["firmware.progress"] | null;
  failure: ServerPayloads["build.failed"] | null;
  done: ServerPayloads["build.done"] | null;
  edit: EditView | null;
  /** Client clock (ms) when build.start was sent. */
  startAt: number | null;
  firstPartMs: number | null;
  doneMs: number | null;
  placeDone: boolean;
  placementSolver: ServerPayloads["placement.updated"]["solver"] | null;
}

export function emptyStages(): Record<string, StageView> {
  const out: Record<string, StageView> = {};
  for (const id of STAGE_IDS) out[id] = { id, status: "pending" };
  return out;
}

export function emptyView(startAt: number | null = null): ViewState {
  return {
    stages: emptyStages(),
    candidates: {},
    reuse: null,
    firmwareProgress: null,
    failure: null,
    done: null,
    edit: null,
    startAt,
    firstPartMs: null,
    doneMs: null,
    placeDone: false,
    placementSolver: null,
  };
}

const ROW_STATUS = new Set<StageRowStatus>(["ok", "skipped", "degraded", "failed", "needs_input"]);

function payload<T extends keyof ServerPayloads>(env: ServerEnvelope<unknown>): ServerPayloads[T] {
  return env.payload as ServerPayloads[T];
}

/** Track edits by msg_id and edit_id (C19). */
export function editSent(view: ViewState, msgId: string, ops: EditOp[], label?: string): ViewState {
  return { ...view, edit: { msg_id: msgId, ops, phase: "pending", label } };
}

function editMatches(view: ViewState, env: ServerEnvelope<unknown>): boolean {
  const e = view.edit;
  if (!e) return false;
  const cause = env.cause;
  if (cause?.msg_id === e.msg_id) return true;
  if (e.edit_id && cause?.edit_id === e.edit_id) return true;
  return false;
}

export function reduceView(view: ViewState, env: ServerEnvelope<unknown>, now: number): ViewState {
  switch (env.type) {
    case "ack": {
      const p = payload<"ack">(env);
      if (view.edit && p.msg_id === view.edit.msg_id) {
        if (!p.accepted) {
          return { ...view, edit: { ...view.edit, phase: "rejected", error: p.error ?? null, edit_id: p.edit_id } };
        }
        return { ...view, edit: { ...view.edit, edit_id: p.edit_id, phase: "applying" } };
      }
      return view;
    }
    case "build.snapshot": {
      const b = payload<"build.snapshot">(env).build;
      const stages = emptyStages();
      for (const [id, ms] of Object.entries(b.timings_ms ?? {})) {
        stages[id] = { ...(stages[id] ?? { id }), status: "ok", duration_ms: ms };
      }
      return {
        ...view,
        stages,
        placeDone: view.placeDone || "place" in (b.timings_ms ?? {}) || b.status === "done",
      };
    }
    case "stage.started": {
      const p = payload<"stage.started">(env);
      if (p.stage === "edit") {
        if (editMatches(view, env) && view.edit) {
          return { ...view, edit: { ...view.edit, phase: "applying", label: p.label ?? view.edit.label } };
        }
        return view;
      }
      const prev = view.stages[p.stage] ?? { id: p.stage };
      return {
        ...view,
        stages: {
          ...view.stages,
          [p.stage]: { ...prev, status: "active", label: p.label, budget_ms: p.budget_ms, startedAt: now, message: null },
        },
      };
    }
    case "stage.progress": {
      const p = payload<"stage.progress">(env);
      const prev = view.stages[p.stage];
      if (!prev) return view;
      return {
        ...view,
        stages: { ...view.stages, [p.stage]: { ...prev, message: p.message, fraction: p.fraction ?? null } },
      };
    }
    case "stage.completed": {
      const p = payload<"stage.completed">(env);
      if (p.stage === "edit") {
        if (editMatches(view, env) && view.edit) return { ...view, edit: { ...view.edit, duration_ms: p.duration_ms } };
        return view;
      }
      const prev = view.stages[p.stage] ?? { id: p.stage };
      const status: StageRowStatus = ROW_STATUS.has(p.status as StageRowStatus) ? (p.status as StageRowStatus) : "unknown";
      return {
        ...view,
        placeDone: view.placeDone || p.stage === "place",
        stages: {
          ...view.stages,
          [p.stage]: { ...prev, status, duration_ms: p.duration_ms, message: p.message ?? prev.message ?? null },
        },
      };
    }
    case "clarify.request": {
      const prev = view.stages.classify ?? { id: "classify" };
      return { ...view, stages: { ...view.stages, classify: { ...prev, status: "needs_input" } } };
    }
    case "reuse.decided":
      return { ...view, reuse: payload<"reuse.decided">(env) };
    case "candidates.ready": {
      const p = payload<"candidates.ready">(env);
      const list = (view.candidates[p.slot_id] ?? []).filter((c) => c.step !== p.step);
      list.push(p);
      list.sort((a, b) => a.step - b.step);
      return { ...view, candidates: { ...view.candidates, [p.slot_id]: list } };
    }
    case "part.added":
      if (view.firstPartMs === null && view.startAt !== null) {
        return { ...view, firstPartMs: Math.max(0, Math.round(now - view.startAt)) };
      }
      return view;
    case "placement.updated":
      return { ...view, placeDone: true, placementSolver: payload<"placement.updated">(env).solver ?? null };
    case "firmware.progress":
      return { ...view, firmwareProgress: payload<"firmware.progress">(env) };
    case "firmware.ready":
      return { ...view, firmwareProgress: null };
    case "build.done":
      return {
        ...view,
        done: payload<"build.done">(env),
        doneMs: view.startAt !== null ? Math.max(0, Math.round(now - view.startAt)) : null,
        placeDone: true,
      };
    case "build.failed": {
      const p = payload<"build.failed">(env);
      const stages = { ...view.stages };
      for (const [id, s] of Object.entries(stages)) if (s.status === "active") stages[id] = { ...s, status: "failed" };
      return { ...view, failure: p, stages };
    }
    case "edit.applied": {
      const p = payload<"edit.applied">(env);
      if (!view.edit || (p.msg_id !== view.edit.msg_id && p.edit_id !== view.edit.edit_id)) return view;
      return { ...view, edit: { ...view.edit, phase: "applied", edit_id: p.edit_id, duration_ms: p.duration_ms } };
    }
    case "edit.rejected": {
      const p = payload<"edit.rejected">(env);
      if (!view.edit || (p.msg_id !== view.edit.msg_id && p.edit_id !== view.edit.edit_id)) return view;
      return {
        ...view,
        edit: {
          ...view.edit,
          phase: "rejected",
          edit_id: p.edit_id,
          error: p.error,
          failed_checks: p.failed_checks ?? [],
          suggestions: p.suggestions ?? [],
        },
      };
    }
    default:
      return view;
  }
}
