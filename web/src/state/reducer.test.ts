import { describe, expect, it, vi } from "vitest";
import { createBuild, reduceBuild, isKnownEvent } from "./reducer";
import { loadFixtures } from "../spec/fixtures";
import type { Build, ClientEnvelope, ServerEnvelope, StreamFixture } from "../spec/types";
import { CONNECTION_SCOPED } from "../spec/types";

const fx = await loadFixtures();

function chain(name: string): StreamFixture[] {
  const f = fx.streams.get(name);
  if (!f) throw new Error(`no fixture ${name}`);
  return f.requires_fixture ? [...chain(f.requires_fixture), f] : [f];
}

/** Replays a fixture chain the way the client store would, returning the Build. */
function replay(
  name: string,
  onUnknown?: (env: ServerEnvelope) => void,
  mutate?: (env: ServerEnvelope) => ServerEnvelope,
  inject?: (env: ServerEnvelope) => ServerEnvelope[],
): Build | null {
  let build: Build | null = null;
  let lastStart: ClientEnvelope<"build.start"> | null = null;
  for (const f of chain(name)) {
    for (const step of f.steps) {
      if (step.dir === "client") {
        if (step.msg.type === "build.start") lastStart = step.msg as ClientEnvelope<"build.start">;
        continue;
      }
      const env = mutate ? mutate(step.msg) : step.msg;
      if (env.type === "ack" && lastStart && (env.payload as { msg_id: string }).msg_id === lastStart.msg_id) {
        build = createBuild((env.payload as { build_id: string }).build_id, lastStart.payload.prompt, lastStart.ts);
        lastStart = null;
        continue;
      }
      if (CONNECTION_SCOPED.has(env.type) || !build) continue;
      for (const e of [...(inject?.(env) ?? []), env]) {
        if (!isKnownEvent(e.type)) onUnknown?.(e);
        build = reduceBuild(build, e);
      }
    }
  }
  return build;
}

const expected: Record<string, { status: string; revision: number; last_seq: number }> = {
  exact_keyboard: { status: "done", revision: 1, last_seq: 62 },
  compose_wireless_split_oled: { status: "done", revision: 1, last_seq: 98 },
  clarify_vague_gadget: { status: "done", revision: 1, last_seq: 58 },
  failed_critical_missing: { status: "failed", revision: 0, last_seq: 14 },
  edit_swap_switches: { status: "done", revision: 2, last_seq: 68 },
  edit_remove_part: { status: "done", revision: 2, last_seq: 67 },
  edit_rejected_choc: { status: "done", revision: 1, last_seq: 65 },
  resume_gap: { status: "done", revision: 1, last_seq: 62 },
};

describe("section 9 reducer", () => {
  it("C6: exact_keyboard reduces to rest/build_exact.json build", () => {
    const rest = fx.rest.find((r) => r.fixture === "build_exact");
    expect(rest).toBeDefined();
    const build = replay("exact_keyboard");
    expect(build).toEqual((rest?.response.body as { build: Build }).build);
  });

  it("covers every stream fixture", () => {
    expect([...fx.streams.keys()].sort()).toEqual(Object.keys(expected).sort());
  });

  for (const [name, want] of Object.entries(expected)) {
    it(`${name} reduces with no throw to ${want.status} r${want.revision}`, () => {
      const build = replay(name);
      expect(build).not.toBeNull();
      expect(build?.status).toBe(want.status);
      expect(build?.revision).toBe(want.revision);
      expect(build?.last_seq).toBe(want.last_seq);
    });
  }

  it("failed build carries the error and no clarify", () => {
    const b = replay("failed_critical_missing");
    expect(b?.error?.code).toBe("E_CRITICAL_PART_MISSING");
    expect(b?.clarify).toBeNull();
  });

  it("clarify flow records both resolutions", () => {
    const b = replay("clarify_vague_gadget");
    expect(b?.clarifications?.map((c) => c.question_id)).toEqual(["q_function", "q_power"]);
    expect(b?.clarify).toBeNull();
  });

  it("C8: unknown fields everywhere and an unknown event type give the same state", () => {
    const base = replay("compose_wireless_split_oled");
    const addUnknown = (v: unknown): unknown => {
      if (Array.isArray(v)) return v.map(addUnknown);
      if (v && typeof v === "object") {
        const o: Record<string, unknown> = {};
        for (const [k, x] of Object.entries(v)) o[k] = addUnknown(x);
        o.x_future_field = { nested: [1, 2, 3] };
        return o;
      }
      return v;
    };
    const stripUnknown = (v: unknown): unknown => {
      if (Array.isArray(v)) return v.map(stripUnknown);
      if (v && typeof v === "object") {
        const o: Record<string, unknown> = {};
        for (const [k, x] of Object.entries(v)) if (k !== "x_future_field") o[k] = stripUnknown(x);
        return o;
      }
      return v;
    };
    const unknownSeen = vi.fn();
    const mutated = replay(
      "compose_wireless_split_oled",
      unknownSeen,
      (env) => addUnknown(env) as ServerEnvelope,
      (env) =>
        env.seq === 10
          ? [{ spec_version: "1.1.0", type: "future.event", seq: 9, build_id: env.build_id, ts: env.ts, payload: { a: 1 } }]
          : [],
    );
    expect(unknownSeen).toHaveBeenCalledTimes(1);
    expect(stripUnknown(mutated)).toEqual(base);

    // A standalone unknown event changes nothing except bookkeeping and is reported.
    const before = base as Build;
    const env: ServerEnvelope = {
      spec_version: "1.1.0",
      type: "future.event",
      seq: before.last_seq + 1,
      build_id: before.build_id,
      ts: "2026-10-24T20:00:09.000Z",
      payload: {},
    };
    expect(isKnownEvent(env.type)).toBe(false);
    expect(reduceBuild(before, env)).toBe(before);
  });
});
