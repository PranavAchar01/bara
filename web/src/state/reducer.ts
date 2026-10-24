// SPEC section 9: the Build reducer. Pure; applying every event of a build in
// seq order must equal GET /v1/builds/{id} (contract C6). The reducer keeps raw
// server data (unknown fields and enum values included); normalisation to
// `unknown` happens only when rendering.
import type { Build, ServerEnvelope, ServerPayloads } from "../spec/types";
import { CONNECTION_SCOPED } from "../spec/types";

/** Event types the reducer knows. Anything else is "unknown" and goes to C29. */
export const KNOWN_BUILD_EVENTS = new Set<string>([
  "build.snapshot",
  "stage.started",
  "stage.progress",
  "stage.completed",
  "clarify.request",
  "clarify.resolved",
  "spec.ready",
  "reuse.decided",
  "slots.ready",
  "slot.updated",
  "candidates.ready",
  "decision.made",
  "decision.reverted",
  "layout.added",
  "part.added",
  "part.updated",
  "part.removed",
  "connection.added",
  "connection.removed",
  "placement.updated",
  "enclosure.updated",
  "board.updated",
  "firmware.ready",
  "firmware.progress",
  "scene.ready",
  "check.result",
  "warning",
  "build.done",
  "build.failed",
  "edit.applied",
  "edit.rejected",
]);

export function isKnownEvent(type: string): boolean {
  return CONNECTION_SCOPED.has(type) || KNOWN_BUILD_EVENTS.has(type);
}

/** The Build created on the ack of a build.start. */
export function createBuild(buildId: string, prompt: string, createdAt?: string): Build {
  const build: Build = {
    build_id: buildId,
    prompt,
    status: "running",
    revision: 0,
    tier: "unknown",
    spec: null,
    design_id: null,
    slots: [],
    decisions: [],
    parts: [],
    connections: [],
    layouts: [],
    enclosures: [],
    boards: [],
    firmware: null,
    checks: [],
    warnings: [],
    scene: null,
    timings_ms: {},
    error: null,
    last_seq: 0,
    clarify: null,
    clarifications: [],
  };
  if (createdAt !== undefined) build.created_at = createdAt;
  return build;
}

function upsert<T, K extends keyof T>(list: T[] | undefined, item: T, key: K): T[] {
  const out = list ? list.slice() : [];
  const i = out.findIndex((x) => x[key] === item[key]);
  if (i >= 0) out[i] = item;
  else out.push(item);
  return out;
}

function without<T, K extends keyof T>(list: T[] | undefined, key: K, value: T[K]): T[] {
  return (list ?? []).filter((x) => x[key] !== value);
}

type Env<T extends keyof ServerPayloads> = ServerEnvelope<ServerPayloads[T]>;
function as<T extends keyof ServerPayloads>(env: ServerEnvelope<unknown>): Env<T> {
  return env as Env<T>;
}

/**
 * Apply one build-scoped event. Returns the same object when nothing changed.
 * Connection-scoped events and unknown types never change the Build.
 */
export function reduceBuild(build: Build, env: ServerEnvelope<unknown>): Build {
  if (CONNECTION_SCOPED.has(env.type)) return build;
  if (env.type === "build.snapshot") return as<"build.snapshot">(env).payload.build;
  if (!KNOWN_BUILD_EVENTS.has(env.type)) return build;

  const b: Build = { ...build };
  switch (env.type) {
    case "spec.ready":
      b.spec = as<"spec.ready">(env).payload.spec;
      break;
    case "reuse.decided": {
      const p = as<"reuse.decided">(env).payload;
      b.tier = p.tier;
      b.design_id = p.design_id;
      break;
    }
    case "slots.ready":
      b.slots = as<"slots.ready">(env).payload.slots;
      break;
    case "slot.updated":
      b.slots = upsert(b.slots, as<"slot.updated">(env).payload.slot, "slot_id");
      break;
    case "decision.made":
      b.decisions = upsert(b.decisions, as<"decision.made">(env).payload.decision, "decision_id");
      break;
    case "decision.reverted":
      b.decisions = without(b.decisions, "decision_id", as<"decision.reverted">(env).payload.decision_id);
      break;
    case "layout.added":
      b.layouts = upsert(b.layouts, as<"layout.added">(env).payload.layout, "layout_id");
      break;
    case "part.added":
    case "part.updated":
      b.parts = upsert(b.parts, as<"part.added">(env).payload.part, "instance_id");
      break;
    case "part.removed":
      b.parts = without(b.parts, "instance_id", as<"part.removed">(env).payload.instance_id);
      break;
    case "connection.added":
      b.connections = upsert(b.connections, as<"connection.added">(env).payload.connection, "connection_id");
      break;
    case "connection.removed":
      b.connections = without(b.connections, "connection_id", as<"connection.removed">(env).payload.connection_id);
      break;
    case "placement.updated": {
      const byId = new Map(as<"placement.updated">(env).payload.placements.map((p) => [p.instance_id, p.placement]));
      b.parts = b.parts.map((part) => {
        const placement = byId.get(part.instance_id);
        return placement ? { ...part, placement } : part;
      });
      break;
    }
    case "enclosure.updated":
      b.enclosures = upsert(b.enclosures, as<"enclosure.updated">(env).payload.enclosure, "enclosure_id");
      break;
    case "board.updated":
      b.boards = upsert(b.boards, as<"board.updated">(env).payload.board, "board_id");
      break;
    case "firmware.ready":
      b.firmware = as<"firmware.ready">(env).payload.firmware;
      break;
    case "scene.ready":
      b.scene = as<"scene.ready">(env).payload.scene;
      break;
    case "check.result":
      for (const r of as<"check.result">(env).payload.results) b.checks = upsert(b.checks, r, "check_key");
      break;
    case "warning":
      b.warnings = upsert(b.warnings, as<"warning">(env).payload.warning, "warning_id");
      break;
    case "stage.completed": {
      const p = as<"stage.completed">(env).payload;
      if (p.stage !== "edit") b.timings_ms = { ...(b.timings_ms ?? {}), [p.stage]: p.duration_ms };
      break;
    }
    case "clarify.request":
      b.clarify = as<"clarify.request">(env).payload;
      b.status = "awaiting_input";
      break;
    case "clarify.resolved":
      b.clarifications = [...(b.clarifications ?? []), as<"clarify.resolved">(env).payload];
      b.clarify = null;
      b.status = "running";
      break;
    case "build.done":
      b.status = "done";
      break;
    case "build.failed": {
      const p = as<"build.failed">(env).payload;
      b.status = p.error.code === "E_CANCELLED" ? "cancelled" : "failed";
      b.error = p.error;
      b.clarify = null;
      break;
    }
    default:
      // stage.started, stage.progress, candidates.ready, firmware.progress,
      // edit.applied, edit.rejected: view state only.
      break;
  }
  if (typeof env.revision === "number") b.revision = env.revision;
  b.last_seq = env.seq;
  return b;
}

/** Fold a list of events onto a build (used by tests and REST replay). */
export function reduceAll(build: Build, events: ServerEnvelope<unknown>[]): Build {
  return events.reduce(reduceBuild, build);
}
