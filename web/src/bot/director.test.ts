import { describe, expect, it } from "vitest";
import type { Build, BuildPart } from "../spec/types";
import type { Beat } from "./agent";
import { beatsFor, DWELL_MS, enqueue } from "./director";

let seq = 0;
const ev = (type: string, payload: unknown, s = ++seq) => ({
  type,
  raw: JSON.stringify({ spec_version: "0.1", type, seq: s, build_id: "b_compose01A", ts: "2026-10-24T09:00:00Z", payload }),
});

const bp = (instance_id: string, part_id: string, label: string, display_name: string): BuildPart => ({
  instance_id,
  part_id,
  label,
  quantity: 1,
  slot_id: null,
  placement: { mode: "single", position_mm: [0, 0, 0], rotation_deg: [0, 0, 0] },
  card: { part_id, display_name, kind: "module" },
});

const build = {
  build_id: "b_compose01A",
  prompt: "a wireless split keyboard with an OLED",
  status: "running",
  revision: 3,
  tier: "compose",
  slots: [{ slot_id: "controller", label: "Controller", function_id: "compute.mcu", criticality: "critical", state: "decided" }],
  parts: [
    bp("u_pcb_l", "pcb:corne_v3_l", "PCB left", "Corne v3 PCB (left)"),
    bp("u_mcu_l", "mod:nice_nano_v2", "Controller left", "nice!nano v2"),
  ],
  connections: [],
  enclosures: [],
  boards: [],
  checks: [],
  warnings: [],
  last_seq: 40,
} as Build;

const one = (type: string, payload: unknown, b: Build | null = build) => {
  const beats = beatsFor(ev(type, payload), b);
  expect(beats).toHaveLength(1);
  return beats[0];
};

describe("director beats", () => {
  it("reads the request", () => {
    const b = one("spec.ready", { spec: { spec_id: "sp_compose01", prompt: "a wireless split keyboard" } });
    expect(b).toMatchObject({ target: { kind: "dom", key: "prompt" }, action: "scan", label: "Reading your request" });
  });

  it("looks at each stage and opens the panel that follows it", () => {
    const s = (stage: string, label?: string) => one("stage.started", { stage, label, budget_ms: 100 });
    expect(s("classify", "Understanding the request")).toMatchObject({
      target: { kind: "dom", key: "stage:classify" },
      action: "look",
      label: "Understanding the request",
    });
    expect(s("classify").open).toBeUndefined();
    expect(s("reuse").open).toEqual({ rightTab: "build" });
    expect(s("compose", "Choosing parts").open).toEqual({ rightTab: "build" });
    expect(s("place").open).toEqual({ rightTab: "design" });
    expect(s("enclose").open).toEqual({ rightTab: "design" });
    expect(s("board").open).toEqual({ rightTab: "code", codeTab: "board" });
    expect(s("firmware").open).toEqual({ rightTab: "code", codeTab: "firmware" });
    // No label from the server: a sensible default.
    expect(s("board").label).toBe("Routing the board");
  });

  it("notices an open design to start from", () => {
    const b = one("reuse.decided", { tier: "compose", design_id: "corne", design: { design_id: "corne", name: "Corne (crkbd)" }, considered: [], unmet_hard: [], reason: "" });
    expect(b).toMatchObject({ target: { kind: "dom", key: "viewport" }, action: "scan", label: "Starting from Corne (crkbd)" });
    expect(one("reuse.decided", { tier: "compose", design_id: null, considered: [], unmet_hard: [], reason: "" }).label).toBe("Designing from scratch");
  });

  it("compares the options that survived the filters", () => {
    // survivors is truncated; count_after is the real count.
    const b = one("candidates.ready", { slot_id: "switches", step: 4, filters: [], count_before: 160, count_after: 112, survivors: [{}, {}] });
    expect(b).toMatchObject({ target: { kind: "dom", key: "tab:build" }, action: "scan", label: "Comparing 112 options" });
  });

  it("picks the decision, by name when the part is known", () => {
    const d = (chosen_part_id: string) => ({ decision: { decision_id: "d2", slot_id: "controller", method: "model_pick", chosen_part_id, reason: "" } });
    expect(one("decision.made", d("mod:nice_nano_v2"))).toMatchObject({
      target: { kind: "dom", key: "decision:d2" },
      action: "pick",
      label: "Chose nice!nano v2",
    });
    // Decisions land before their parts: fall back to the slot.
    expect(one("decision.made", d("mod:xiao_ble")).label).toBe("Picking the Controller");
  });

  it("drops each part as it lands", () => {
    const b = one("part.added", { part: bp("u_oled_l", "disp:ssd1306", "OLED left", "SSD1306 OLED 128x32 (I2C)") });
    expect(b).toMatchObject({ target: { kind: "part", id: "u_oled_l" }, action: "drop", label: "Placing OLED left", dwellMs: DWELL_MS.drop });
    const noLabel = { ...bp("u_x", "p", "", "Gateron Yellow (MX)"), label: undefined };
    expect(one("part.added", { part: noLabel }).label).toBe("Placing Gateron Yellow (MX)");
  });

  it("scans once for a whole placement pass", () => {
    const placements = ["u_pcb_l", "u_mcu_l", "u_sw_l"].map((instance_id) => ({ instance_id, placement: {} }));
    expect(one("placement.updated", { placements })).toMatchObject({ target: { kind: "dom", key: "viewport" }, action: "scan", label: "Arranging parts" });
  });

  it("traces a connection with short names and opens connections", () => {
    const b = one("connection.added", {
      connection: { connection_id: "c_mcu_pcb_l", type: "module_footprint", kind: "mechanical", from: { instance_id: "u_pcb_l", interface_id: "mcu_socket" }, to: { instance_id: "u_mcu_l", interface_id: "footprint" } },
    });
    expect(b.target).toEqual({ kind: "part", id: "u_pcb_l" });
    expect(b.action).toBe("trace");
    expect(b.label).toMatch(/^Wiring PCB left → Control/);
    expect(b.label.length).toBeLessThan(32);
    expect(b.open).toEqual({ rightTab: "code", codeTab: "connections" });
  });

  it("shapes the case, routes the board, writes firmware", () => {
    expect(one("enclosure.updated", { enclosure: { enclosure_id: "e_case_l" } })).toMatchObject({ action: "scan", label: "Shaping the case" });
    expect(one("board.updated", { board: { board_id: "pcb_l" } })).toMatchObject({
      target: { kind: "dom", key: "viewport" },
      action: "trace",
      open: { rightTab: "code", codeTab: "board" },
    });
    for (const type of ["firmware.progress", "firmware.ready"]) {
      expect(one(type, { firmware_id: "fw_main", phase: "compiling" })).toMatchObject({
        target: { kind: "dom", key: "codetab:firmware" },
        action: "type",
        label: "Writing firmware",
        dwellMs: DWELL_MS.type,
      });
    }
  });

  it("checks results, failures first, at most two", () => {
    const r = (check_key: string, status: string, subjects: unknown[]) => ({ check_key, rule_id: check_key, status, severity: "error", message: `${check_key} ${status}`, subjects });
    const beats = beatsFor(
      ev("check.result", {
        results: [
          r("mech.fit.enclosure:e_case_l", "pass", [{ enclosure_id: "e_case_l" }]),
          r("elec.i2c.address_clash:u_mcu_l", "pass", [{ instance_id: "u_mcu_l", interface_id: "i2c0" }]),
          r("slot.optional_missing:foam", "fail", []),
        ],
      }),
      build,
    );
    expect(beats).toHaveLength(2);
    expect(beats[0]).toMatchObject({ target: { kind: "dom", key: "check:slot.optional_missing:foam" }, action: "check", bad: true });
    expect(beats[1]).toMatchObject({ target: { kind: "dom", key: "check:mech.fit.enclosure:e_case_l" }, action: "check" });
    expect(beats[1].bad).toBeUndefined();
    expect(new Set(beats.map((b) => b.id)).size).toBe(2);

    const onPart = beatsFor(ev("check.result", { results: [r("elec.i2c.address_clash:u_mcu_l", "pass", [{ instance_id: "u_mcu_l" }])] }), build);
    expect(onPart[0].target).toEqual({ kind: "part", id: "u_mcu_l" });
    expect(beatsFor(ev("check.result", { results: [] }), build)).toEqual([]);
  });

  it("frowns at warnings", () => {
    const b = one("warning", {
      warning: { warning_id: "w1", code: "licence_unknown", severity: "warning", message: "nice!nano v2 has no declared hardware licence.", subjects: [{ part_id: "mod:nice_nano_v2", instance_id: "u_mcu_l" }] },
    });
    expect(b).toMatchObject({ target: { kind: "part", id: "u_mcu_l" }, action: "look", bad: true });
    expect(b.label.length).toBeLessThan(32);
    expect(one("warning", { warning: { warning_id: "w2", code: "x", message: "Case foam left out", subjects: [{ slot_id: "foam" }] } }).target).toEqual({ kind: "dom", key: "viewport" });
  });

  it("cheers when done and looks worried when it fails", () => {
    expect(one("build.done", { summary: { instance_count: 14 } })).toMatchObject({ target: { kind: "dom", key: "viewport" }, action: "cheer", label: "Done" });
    expect(one("build.failed", { error: { code: "x", message: "no", retryable: false } }, null)).toMatchObject({ action: "look", bad: true, label: "That didn't work" });
  });

  it("ignores everything else and survives junk", () => {
    expect(beatsFor(ev("slots.ready", { slots: [] }), build)).toEqual([]);
    expect(beatsFor(ev("hello", {}), null)).toEqual([]);
    expect(beatsFor({ type: "part.added", raw: "not json" }, null)).toEqual([]);
    expect(beatsFor({ type: "placement.updated" }, null)).toHaveLength(1);
  });

  it("keys beats by seq so they are stable and unique", () => {
    const a = beatsFor(ev("placement.updated", {}, 75), build)[0];
    const again = beatsFor(ev("placement.updated", {}, 75), build)[0];
    const next = beatsFor(ev("placement.updated", {}, 76), build)[0];
    expect(a.id).toBe("placement.updated:75");
    expect(again.id).toBe(a.id);
    expect(next.id).not.toBe(a.id);
  });

  it("keeps every label on the chip", () => {
    const b = one("stage.started", { stage: "compose", label: "x".repeat(80) });
    expect(b.label.length).toBeLessThan(32);
  });
});

const mk = (id: string, action: Beat["action"], key = "viewport", extra: Partial<Beat> = {}): Beat => ({
  id,
  target: { kind: "dom", key },
  action,
  label: id,
  dwellMs: 600,
  ...extra,
});
const drop = (id: string, inst: string): Beat => ({ id, target: { kind: "part", id: inst }, action: "drop", label: id, dwellMs: 700 });
const ids = (q: Beat[]) => q.map((b) => b.id);

describe("director queue", () => {
  it("appends in order and skips beats it already has", () => {
    const q = enqueue([mk("a", "look")], [mk("b", "pick"), mk("a", "look")]);
    expect(ids(q)).toEqual(["a", "b"]);
  });

  it("does not mutate the queue it was given", () => {
    const q = [mk("a", "look")];
    enqueue(q, [mk("b", "pick")]);
    expect(ids(q)).toEqual(["a"]);
  });

  it("drops glances before real work when it runs long", () => {
    const q = enqueue([mk("p1", "pick", "decision:d1"), mk("l1", "look", "stage:compose"), mk("d1", "drop", "x"), mk("s1", "scan", "tab:build")], [
      mk("p2", "pick", "decision:d2"),
      mk("p3", "pick", "decision:d3"),
      mk("p4", "pick", "decision:d4"),
    ]);
    expect(q).toHaveLength(6);
    expect(ids(q)).toEqual(["p1", "d1", "s1", "p2", "p3", "p4"]);
    // Out of glances: the oldest real work goes next.
    expect(ids(enqueue(q, [mk("p5", "pick", "decision:d5"), mk("p6", "pick", "decision:d6")]))).toEqual(["d1", "p2", "p3", "p4", "p5", "p6"]);
  });

  it("never drops a cheer or a problem", () => {
    const bad = mk("w", "look", "viewport", { bad: true });
    const q = enqueue([bad, mk("a", "pick"), mk("b", "pick")], [mk("c", "pick"), mk("done", "cheer")], 3);
    expect(ids(q)).toEqual(["w", "c", "done"]);
    // All protected: keep them all rather than lose one.
    expect(ids(enqueue([bad, mk("w2", "check", "x", { bad: true })], [mk("done", "cheer")], 2))).toEqual(["w", "w2", "done"]);
  });

  it("collapses back-to-back scans of the same thing into the newest", () => {
    const q = enqueue([mk("s1", "scan", "viewport")], [mk("s2", "scan", "viewport"), mk("s3", "scan", "tab:build"), mk("s4", "scan", "tab:build")]);
    expect(ids(q)).toEqual(["s2", "s4"]);
    // Not consecutive: both stay.
    expect(ids(enqueue([mk("s1", "scan"), mk("p", "pick")], [mk("s2", "scan")]))).toEqual(["s1", "p", "s2"]);
  });

  it("replaces an older drop on the same part", () => {
    const q = enqueue([drop("old", "u_mcu_l"), drop("other", "u_pcb_l"), mk("p", "pick")], [drop("new", "u_mcu_l")]);
    expect(ids(q)).toEqual(["other", "p", "new"]);
  });

  it("defaults to six beats", () => {
    const many = Array.from({ length: 10 }, (_, i) => mk(`p${i}`, "pick", `decision:d${i}`));
    expect(enqueue([], many)).toHaveLength(6);
    expect(enqueue([], many, 3)).toHaveLength(3);
  });

  it("keeps a full event stream short and ends on the cheer", () => {
    let q: Beat[] = [];
    const stream = [
      ev("spec.ready", {}),
      ev("stage.started", { stage: "compose" }),
      ...["u_pcb_l", "u_mcu_l", "u_bat_l", "u_oled_l", "u_sw_l"].map((id) => ev("part.added", { part: bp(id, id, id, id) })),
      ev("warning", { warning: { warning_id: "w1", message: "No licence" } }),
      ev("placement.updated", {}),
      ev("build.done", {}),
    ];
    for (const e of stream) q = enqueue(q, beatsFor(e, build));
    expect(q.length).toBeLessThanOrEqual(6);
    expect(q[q.length - 1].action).toBe("cheer");
    expect(q.some((b) => b.bad)).toBe(true);
  });
});
