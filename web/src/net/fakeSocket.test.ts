import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { loadFixtures } from "../spec/fixtures";
import type { Build, ClientEnvelope, EditOp, ServerEnvelope, ServerPayloads } from "../spec/types";
import { createBuild, reduceBuild } from "../state/reducer";
import { Connection } from "./connection";
import { FakeSocket, fixtureBuildPath, MockHub, MockServer, MOCK_EDIT_MESSAGE, pacedDelays, selectEditFixture, selectFixture } from "./fakeSocket";
import { RestClient, paths, stubFetcher } from "./rest";

const fx = await loadFixtures();

function harness(opts: { forced?: string | null; speed?: number } = {}) {
  const server = new MockServer(fx, { speed: opts.speed ?? 1, forcedFixture: opts.forced ?? null });
  const received: ServerEnvelope[] = [];
  const sent: ClientEnvelope[] = [];
  const state: { build: Build | null; start: { id: string; prompt: string; ts: string } | null } = {
    build: null,
    start: null,
  };
  let n = 0;
  const conn: Connection = new Connection({
    url: "mock",
    socketFactory: () => new FakeSocket(server),
    resumeTarget: () => (state.build ? { build_id: state.build.build_id, last_seq: state.build.last_seq } : null),
    onEnvelope: (env) => {
      received.push(env);
      if (env.type === "ack" && state.start) {
        const p = env.payload as ServerPayloads["ack"];
        if (p.msg_id === state.start.id && p.build_id) {
          state.build = createBuild(p.build_id, state.start.prompt, state.start.ts);
          conn.setCursor(p.build_id, 0);
          state.start = null;
        }
        return;
      }
      if (state.build && env.build_id === state.build.build_id && env.seq > 0) state.build = reduceBuild(state.build, env);
    },
    onSent: (env) => sent.push(env),
    idFactory: () => `m_real_${String(++n).padStart(4, "0")}`,
  });
  conn.connect();
  return {
    conn,
    received,
    sent,
    state,
    start(prompt: string) {
      const id = conn.send("build.start", { prompt });
      state.start = { id, prompt, ts: new Date().toISOString() };
      return id;
    },
  };
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

async function run(ms = 120_000) {
  await vi.advanceTimersByTimeAsync(ms);
}

describe("mock fixture selection", () => {
  it("matches prompts case-insensitively and falls back to the compose fixture", () => {
    expect(selectFixture(fx, "  A Keyboard ")).toBe("exact_keyboard");
    expect(selectFixture(fx, "make me a gadget")).toBe("clarify_vague_gadget");
    expect(selectFixture(fx, "a toaster that tweets")).toBe("compose_wireless_split_oled");
    expect(selectFixture(fx, "a keyboard", "failed_critical_missing")).toBe("failed_critical_missing");
  });

  it("matches edits by op list", () => {
    const swap: EditOp[] = [
      { op: "swap_part", instance_id: "u_sw_l", part_id: "sw:cherry_mx2a_brown" },
      { op: "swap_part", instance_id: "u_sw_r", part_id: "sw:cherry_mx2a_brown" },
    ];
    expect(selectEditFixture(fx, swap)).toBe("edit_swap_switches");
    expect(selectEditFixture(fx, [{ op: "remove_part", instance_id: "u_oled_l" }])).toBe("edit_remove_part");
    expect(selectEditFixture(fx, [{ op: "remove_part", instance_id: "u_mcu_l" }])).toBeNull();
  });
});

describe("mock replay", () => {
  it("replays exact_keyboard to the C6 state and rewrites msg_ids", async () => {
    const h = harness();
    await run(100);
    expect(h.conn.ready).toBe(true);
    const id = h.start("a keyboard");
    await run();
    const ack = h.received.find((e) => e.type === "ack");
    expect((ack?.payload as { msg_id: string }).msg_id).toBe(id);
    const rest = fx.rest.find((r) => r.fixture === "build_exact")?.response.body as { build: Build };
    const { created_at: _a, ...got } = h.state.build as Build;
    const { created_at: _b, ...want } = rest.build;
    expect(got).toEqual(want);
    expect(h.received.filter((e) => e.cause?.msg_id).every((e) => e.cause?.msg_id === id)).toBe(true);
  });

  it("pauses at clarify steps until the UI answers", async () => {
    const h = harness();
    await run(100);
    h.start("something cool for my desk");
    await run();
    expect(h.state.build?.status).toBe("awaiting_input");
    const q = h.state.build?.clarify;
    expect(q?.question_id).toBe("q_function");
    const a1 = h.conn.send("clarify.answer", { build_id: "b_clarify01", question_id: "q_function", option_id: "o_weather" });
    await run(10_000);
    const acks = h.received.filter((e) => e.type === "ack").map((e) => (e.payload as { msg_id: string }).msg_id);
    expect(acks).toContain(a1);
    expect(h.state.build?.clarify?.question_id).toBe("q_power");
    h.conn.send("clarify.answer", { build_id: h.state.build?.build_id ?? "", question_id: "q_power", skip: true });
    await run();
    expect(h.state.build?.status).toBe("done");
    expect(h.state.build?.clarifications).toHaveLength(2);
  });

  it("plays a matching edit fixture with the real ids", async () => {
    const h = harness();
    await run(100);
    h.start("keyboard");
    await run();
    const ops: EditOp[] = [
      { op: "swap_part", instance_id: "u_sw_l", part_id: "sw:cherry_mx2a_brown" },
      { op: "swap_part", instance_id: "u_sw_r", part_id: "sw:cherry_mx2a_brown" },
    ];
    const id = h.conn.send("edit.apply", { build_id: "b_exact001A", base_revision: 1, ops });
    await run(5_000);
    const applied = h.received.find((e) => e.type === "edit.applied");
    expect((applied?.payload as { msg_id: string }).msg_id).toBe(id);
    expect(h.state.build?.revision).toBe(2);
    expect(h.state.build?.parts.find((p) => p.instance_id === "u_sw_l")?.part_id).toBe("sw:cherry_mx2a_brown");
    // A second edit continues seq and revision.
    const id2 = h.conn.send("edit.apply", { build_id: "b_exact001A", ops: [{ op: "remove_part", instance_id: "u_oled_l" }] });
    await run(5_000);
    const applied2 = h.received.filter((e) => e.type === "edit.applied")[1];
    expect((applied2?.payload as { msg_id: string; edit_id: string }).msg_id).toBe(id2);
    expect((applied2?.payload as { edit_id: string }).edit_id).toBe("ed_2");
    expect(h.state.build?.revision).toBe(3);
    expect(h.state.build?.last_seq).toBe(68 + 5);
    expect(h.state.build?.parts.some((p) => p.instance_id === "u_oled_l")).toBe(false);
  });

  it("rejects unmatched edits with the mock message", async () => {
    const h = harness();
    await run(100);
    h.start("keyboard");
    await run();
    h.conn.send("edit.apply", { build_id: "b_exact001A", ops: [{ op: "remove_part", instance_id: "u_mcu_l" }] });
    await run(5_000);
    const rej = h.received.find((e) => e.type === "edit.rejected");
    expect((rej?.payload as ServerPayloads["edit.rejected"]).error.message).toBe(MOCK_EDIT_MESSAGE);
    expect(h.state.build?.revision).toBe(1);
  });

  it("chains forced fixtures and cancels a running build", async () => {
    const h = harness({ forced: "failed_critical_missing" });
    await run(100);
    h.start("anything");
    await run();
    expect(h.state.build?.status).toBe("failed");

    const h2 = harness();
    await run(100);
    h2.start("a wireless split keyboard with an OLED");
    await run(300);
    h2.conn.send("build.cancel", { build_id: h2.state.build?.build_id ?? "" });
    await run(1_000);
    expect(h2.state.build?.status).toBe("cancelled");
  });

  it("forced resume_gap drops the socket and recovers from a snapshot", async () => {
    const h = harness({ forced: "resume_gap" });
    await run(100);
    h.start("a keyboard");
    await run(60_000);
    expect(h.received.some((e) => e.type === "build.snapshot")).toBe(true);
    expect(h.state.build?.status).toBe("done");
    expect(h.conn.state).toBe("open");
  });
});

describe("REST stub", () => {
  it("answers by method and path, else E_NOT_FOUND", async () => {
    const rest = new RestClient(stubFetcher(fx.rest));
    const alt = await rest.get(paths.alternatives("b_exact001A", "switches", "u_sw_l"));
    expect(alt.ok).toBe(true);
    const part = await rest.get<{ part: { part_id: string } }>(paths.part("mod:nice_nano_v2"));
    expect(part.ok).toBe(true);
    const missing = await rest.get(paths.part("mod:nope"));
    expect(missing.ok).toBe(false);
    if (!missing.ok) expect(missing.error.code).toBe("E_NOT_FOUND");
  });
});

describe("mock hub (several canvases)", () => {
  it("runs two builds of one fixture at once under different build ids", async () => {
    const hub = new MockHub(fx, { speed: 1 });
    const builds = new Map<string, Build>();
    const starts = new Map<string, string>();
    const conn: Connection = new Connection({
      url: "mock",
      socketFactory: () => new FakeSocket(hub),
      resumeTarget: () => null,
      onEnvelope: (env) => {
        if (env.type === "ack") {
          const p = env.payload as ServerPayloads["ack"];
          const prompt = starts.get(p.msg_id);
          if (prompt && p.build_id) {
            builds.set(p.build_id, createBuild(p.build_id, prompt));
            conn.setCursor(p.build_id, 0);
          }
          return;
        }
        const b = env.build_id ? builds.get(env.build_id) : undefined;
        if (b && env.seq > 0) builds.set(b.build_id, reduceBuild(b, env));
      },
    });
    conn.connect();
    starts.set(conn.send("build.start", { prompt: "a toaster that tweets" }), "a");
    await run(300);
    starts.set(conn.send("build.start", { prompt: "a toaster that tweets" }), "b");
    await run();
    const ids = [...builds.keys()];
    expect(ids).toHaveLength(2);
    expect(ids[0]).not.toBe(ids[1]);
    expect(ids.map((id) => id.split("~")[0])).toEqual([ids[0].split("~")[0], ids[0].split("~")[0]]);
    expect(fixtureBuildPath(paths.build(ids[1]))).toBe(paths.build(ids[0].split("~")[0]));
    for (const b of builds.values()) {
      expect(b.status).toBe("done");
      expect(b.parts.length).toBeGreaterThan(0);
    }
    expect(builds.get(ids[0])?.parts.length).toBe(builds.get(ids[1])?.parts.length);
  });
});

describe("mock pacing", () => {
  const buildTime = (name: string) => {
    const f = fx.streams.get(name);
    if (!f) throw new Error(name);
    const start = f.steps.findIndex((s) => s.dir === "client" && s.msg.type === "build.start");
    const steps = f.steps.slice(start + 1);
    const delays = pacedDelays(steps);
    const end = steps.findIndex((s) => s.dir === "server" && (s.msg.type === "build.done" || s.msg.type === "build.failed"));
    return delays.slice(0, end + 1).reduce((a, b) => a + b, 0);
  };

  it("spaces a build out to a watchable 12 to 21 s at mock_speed=1", () => {
    for (const name of ["exact_keyboard", "compose_wireless_split_oled"]) {
      const ms = buildTime(name);
      expect(ms, name).toBeGreaterThanOrEqual(12_000);
      expect(ms, name).toBeLessThanOrEqual(21_000);
    }
  });

  it("keeps the fixture's own delays after the build ends and for edits", () => {
    const f = fx.streams.get("compose_wireless_split_oled");
    const steps = f?.steps.slice(f.steps.findIndex((s) => s.dir === "client") + 1) ?? [];
    const delays = pacedDelays(steps);
    const done = steps.findIndex((s) => s.dir === "server" && s.msg.type === "build.done");
    steps.slice(done + 1).forEach((s, i) => expect(delays[done + 1 + i]).toBe(s.dir === "server" ? (s.delay_ms ?? 0) : 0));
    const edit = fx.streams.get("edit_swap_switches")?.steps ?? [];
    expect(pacedDelays(edit, false)).toEqual(edit.map((s) => (s.dir === "server" ? (s.delay_ms ?? 0) : 0)));
  });

  it("is still building after a few seconds and done after the paced time; mock_speed scales it", async () => {
    const h = harness();
    await run(100);
    h.start("a keyboard");
    await run(4_000);
    expect(h.state.build?.status).toBe("running");
    await run(20_000);
    expect(h.state.build?.status).toBe("done");

    const fast = harness({ speed: 0.1 });
    await run(100);
    fast.start("a keyboard");
    await run(2_500);
    expect(fast.state.build?.status).toBe("done");
  });
});
