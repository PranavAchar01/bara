import { describe, expect, it } from "vitest";
import type { ServerEnvelope } from "../spec/types";
import { emptyView, reduceView, type ViewState } from "./view";

let seq = 0;
function env(type: string, payload: Record<string, unknown>, revision?: number): ServerEnvelope {
  return { spec_version: "1", type, seq: ++seq, build_id: "b_hist", ts: "2026-10-24T00:00:00Z", payload, ...(revision !== undefined ? { revision } : {}) } as unknown as ServerEnvelope;
}

/** One edit as the engine streams it: the edit stage starts (with its label), then edit.applied. */
function edit(view: ViewState, revision: number, label: string): ViewState {
  const started = reduceView(view, env("stage.started", { stage: "edit", label }), 0);
  return reduceView(started, env("edit.applied", { edit_id: `ed_${revision}`, msg_id: `m${revision}`, ops: [], revision, duration_ms: 1 }, revision), 0);
}

function restore(view: ViewState, to: number, revision: number): ViewState {
  return reduceView(view, env("build.snapshot", { build: { revision, status: "done", timings_ms: {} }, reason: "restore", restored_from: to }, revision), 0);
}

describe("version history", () => {
  it("starts with the built version once the first edit lands", () => {
    const v = edit(emptyView(), 3, "Recolour the keycaps");
    expect(v.history).toEqual([
      { revision: 2, label: "Built" },
      { revision: 3, label: "Recolour the keycaps" },
    ]);
    expect(v.historyAt).toBe(1);
  });

  it("moves along the versions on undo and redo, and an edit after an undo drops the undone ones", () => {
    let v = edit(edit(emptyView(), 3, "Blue keycaps"), 4, "Add a knob");
    v = restore(v, 3, 5); // undo
    expect(v.historyAt).toBe(1);
    v = restore(v, 4, 6); // redo
    expect(v.historyAt).toBe(2);
    v = restore(v, 2, 7); // back to the build itself
    expect(v.historyAt).toBe(0);
    v = edit(v, 8, "Remove the knob");
    expect(v.history.map((h) => h.label)).toEqual(["Built", "Remove the knob"]);
    expect(v.historyAt).toBe(1);
  });

  it("labels an edit from its ops when the stage gave no label", () => {
    const v = reduceView(emptyView(), env("edit.applied", { edit_id: "ed_1", msg_id: "m", ops: [{ op: "remove_part", instance_id: "k1" }], revision: 2, duration_ms: 1 }, 2), 0);
    expect(v.history[1].label).toBe("Remove");
  });
});
