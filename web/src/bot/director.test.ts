import { describe, expect, it } from "vitest";
import type { Build, BuildPart } from "../spec/types";
import type { Beat } from "./agent";
import { beatsFor, DWELL_MS, enqueue, once, paceFor, QUEUE_MAX } from "./director";

let seq = 0;
const ev = (type: string, payload: unknown, s = ++seq) => ({
  type,
  raw: JSON.stringify({ spec_version: "0.1", type, seq: s, build_id: "b_compose01A", ts: "2026-10-24T09:00:00Z", payload }),
});

const bp = (instance_id: string, part_id: string, label: string, display_name: string, kind = "module", slot_id: string | null = null): BuildPart => ({
  instance_id,
  part_id,
  label,
  quantity: 1,
  slot_id,
  placement: { mode: "single", position_mm: [0, 0, 0], rotation_deg: [0, 0, 0] },
  card: { part_id, display_name, kind },
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
  it("ignores minor steps", () => {
    const minor: [string, unknown][] = [
      ["spec.ready", { spec: { spec_id: "sp_compose01", prompt: "a wireless split keyboard" } }],
      ["stage.started", { stage: "board", label: "Routing the board", budget_ms: 100 }],
      ["candidates.ready", { slot_id: "switches", step: 4, filters: [], count_before: 160, count_after: 112, survivors: [{}, {}] }],
      ["decision.made", { decision: { decision_id: "d2", slot_id: "controller", method: "model_pick", chosen_part_id: "mod:nice_nano_v2", reason: "" } }],
      ["placement.updated", { placements: [{ instance_id: "u_pcb_l", placement: {} }] }],
      ["connection.added", { connection: { connection_id: "c1", from: { instance_id: "u_pcb_l" }, to: { instance_id: "u_mcu_l" } } }],
      ["warning", { warning: { warning_id: "w1", code: "licence_unknown", message: "No licence", subjects: [{ instance_id: "u_mcu_l" }] } }],
    ];
    for (const [type, payload] of minor) expect(beatsFor(ev(type, payload), build)).toEqual([]);
  });

  it("notices an open design to start from", () => {
    const b = one("reuse.decided", { tier: "compose", design_id: "corne", design: { design_id: "corne", name: "Corne (crkbd)" }, considered: [], unmet_hard: [], reason: "" });
    expect(b).toMatchObject({ target: { kind: "dom", key: "viewport" }, action: "scan", label: "Starting from Corne (crkbd)" });
    expect(one("reuse.decided", { tier: "compose", design_id: null, considered: [], unmet_hard: [], reason: "" }).label).toBe("Designing from scratch");
  });

  it("flies to the first major part per slot only", () => {
    const b = one("part.added", { part: bp("u_oled_l", "disp:ssd1306", "OLED left", "SSD1306 OLED 128x32 (I2C)", "module", "display") });
    expect(b).toMatchObject({ target: { kind: "part", id: "u_oled_l" }, action: "drop", label: "Placing OLED left", dwellMs: DWELL_MS.drop });
    const noLabel = { ...bp("u_x", "p", "", "Gateron Yellow (MX)", "component"), label: undefined };
    expect(one("part.added", { part: noLabel }).label).toBe("Placing Gateron Yellow (MX)");

    // The other half of a split, or a second copy, is not news once its slot is on the build.
    const withLeft = { ...build, parts: [...build.parts, bp("u_oled_l", "disp:ssd1306", "OLED left", "SSD1306", "module", "display")] } as Build;
    expect(beatsFor(ev("part.added", { part: bp("u_oled_r", "disp:ssd1306", "OLED right", "SSD1306", "module", "display") }), withLeft)).toEqual([]);
    // The part that is itself already on the build does not count as another instance.
    expect(beatsFor(ev("part.added", { part: bp("u_oled_l", "disp:ssd1306", "OLED left", "SSD1306", "module", "display") }), withLeft)).toHaveLength(1);
    // A different slot still gets its visit.
    expect(beatsFor(ev("part.added", { part: bp("u_bat_l", "bat:lipo", "Battery left", "LiPo", "component", "battery") }), withLeft)).toHaveLength(1);
  });

  it("skips plates, PCBs and caps", () => {
    for (const kind of ["plate", "pcb", "cap", "cable", "switch_cap"]) {
      expect(beatsFor(ev("part.added", { part: bp(`u_${kind}`, `p:${kind}`, kind, kind, kind) }), build)).toEqual([]);
    }
  });

  it("visits board/firmware/case once by id", () => {
    const c = one("enclosure.updated", { enclosure: { enclosure_id: "e_case_l" } });
    expect(c).toMatchObject({ id: once("case"), target: { kind: "dom", key: "viewport" }, action: "scan", label: "Shaping the case", open: { rightTab: "design" } });
    const bd = one("board.updated", { board: { board_id: "pcb_l" } });
    expect(bd).toMatchObject({ id: once("board"), target: { kind: "dom", key: "viewport" }, action: "trace", open: { rightTab: "code", codeTab: "board" } });
    for (const type of ["firmware.progress", "firmware.ready"]) {
      expect(one(type, { firmware_id: "fw_main", phase: "compiling" })).toMatchObject({
        id: once("firmware"),
        target: { kind: "dom", key: "codetab:firmware" },
        action: "type",
        label: "Writing firmware",
        dwellMs: DWELL_MS.type,
        open: { rightTab: "code", codeTab: "firmware" },
      });
    }
    // Repeated events carry the same id, so the stage plays each visit once.
    expect(one("board.updated", { board: { board_id: "pcb_r" } }).id).toBe(bd.id);
    expect(enqueue(enqueue([], [bd]), [one("board.updated", {})])).toHaveLength(1);
  });

  it("only a failing check is worth a beat", () => {
    const r = (check_key: string, status: string, subjects: unknown[], severity = "error") => ({ check_key, rule_id: check_key, status, severity, message: `${check_key} ${status}`, subjects });
    const passing = beatsFor(
      ev("check.result", {
        results: [r("mech.fit.enclosure:e_case_l", "pass", [{ enclosure_id: "e_case_l" }]), r("elec.i2c.address_clash:u_mcu_l", "pass", [{ instance_id: "u_mcu_l" }])],
      }),
      build,
    );
    expect(passing).toEqual([]);

    const beats = beatsFor(
      ev("check.result", {
        results: [
          r("mech.fit.enclosure:e_case_l", "pass", [{ enclosure_id: "e_case_l" }]),
          r("slot.optional_missing:foam", "fail", [], "info"),
          r("licence.unknown:u_mcu_l", "fail", [], "warning"),
          r("elec.i2c.address_clash:u_mcu_l", "fail", [{ instance_id: "u_mcu_l" }], "critical"),
          r("mech.fit.enclosure:e_case_r", "fail", []),
        ],
      }),
      build,
    );
    // Info and warning fails are skipped; only the first error/critical failure gets a beat.
    expect(beats).toHaveLength(1);
    expect(beats[0]).toMatchObject({ target: { kind: "part", id: "u_mcu_l" }, action: "check", bad: true });
    expect(beatsFor(ev("check.result", { results: [r("slot.optional_missing:foam", "fail", [], "info"), r("licence.unknown:x", "fail", [], "warning")] }), build)).toEqual([]);

    const onPart = beatsFor(ev("check.result", { results: [r("elec.i2c.address_clash:u_mcu_l", "fail", [{ instance_id: "u_mcu_l" }])] }), build);
    expect(onPart[0].target).toEqual({ kind: "part", id: "u_mcu_l" });
    expect(beatsFor(ev("check.result", { results: [] }), build)).toEqual([]);
  });

  it("cheers when done and looks worried when it fails", () => {
    expect(one("build.done", { summary: { instance_count: 14 } })).toMatchObject({ target: { kind: "dom", key: "viewport" }, action: "cheer", label: "Done" });
    expect(one("build.failed", { error: { code: "x", message: "no", retryable: false } }, null)).toMatchObject({ action: "look", bad: true, label: "That didn't work" });
  });

  it("ignores everything else and survives junk", () => {
    expect(beatsFor(ev("slots.ready", { slots: [] }), build)).toEqual([]);
    expect(beatsFor(ev("hello", {}), null)).toEqual([]);
    expect(beatsFor({ type: "part.added", raw: "not json" }, null)).toEqual([]);
    expect(beatsFor({ type: "placement.updated" }, null)).toEqual([]);
  });

  it("keys beats by seq so they are stable and unique", () => {
    const part = (seq: number) => beatsFor(ev("part.added", { part: bp("u_oled_l", "disp:ssd1306", "OLED left", "SSD1306", "module", "display") }, seq), build)[0];
    const a = part(75);
    expect(a.id).toBe("part.added:75");
    expect(part(75).id).toBe(a.id);
    expect(part(76).id).not.toBe(a.id);
  });

  it("keeps the board visit through a long queue", () => {
    const routed = beatsFor(ev("board.updated", { board: { board_id: "pcb_l" } }), build);
    expect(routed).toHaveLength(1);
    expect(routed[0].action).toBe("trace");
    expect(routed[0].dwellMs).toBe(DWELL_MS.trace);
    // Real work: traces survive a long queue that drops glances.
    let q: Beat[] = [];
    for (let i = 0; i < 12; i++) q = enqueue(q, [mk(`l${i}`, "look", `stage:s${i}`)]);
    q = enqueue(q, routed);
    expect(q.filter((b) => b.action === "trace")).toHaveLength(1);
  });

  it("acts an applied edit out on the parts it touched", () => {
    const swapped = {
      ...build,
      parts: [
        ...build.parts,
        bp("u_sw_l", "sw:cherry_mx2a_brown", "Switches left", "Cherry MX2A Brown"),
        bp("u_sw_r", "sw:cherry_mx2a_brown", "Switches right", "Cherry MX2A Brown"),
      ],
    } as Build;
    const beats = beatsFor(
      ev("edit.applied", {
        edit_id: "ed_1",
        msg_id: "m1",
        revision: 2,
        duration_ms: 20,
        ops: [
          { op: "swap_part", instance_id: "u_sw_l", part_id: "sw:cherry_mx2a_brown" },
          { op: "swap_part", instance_id: "u_sw_r", part_id: "sw:cherry_mx2a_brown" },
        ],
      }),
      swapped,
    );
    expect(beats).toHaveLength(2);
    expect(beats[0]).toMatchObject({ target: { kind: "part", id: "u_sw_l" }, action: "drop", label: "Swapped to Cherry MX2A Brown" });
    expect(beats[1].target).toEqual({ kind: "part", id: "u_sw_r" });
    expect(new Set(beats.map((b) => b.id)).size).toBe(2);

    const moved = one("edit.applied", { edit_id: "ed_2", ops: [{ op: "move", instance_id: "u_mcu_l", mode: "delta", position_mm: [1, 0, 0] }] });
    expect(moved).toMatchObject({ target: { kind: "part", id: "u_mcu_l" }, action: "pick", label: "Moved Controller left" });
    // The swapped-in part not on the build yet: name it by its id, never by the part it replaced.
    expect(one("edit.applied", { edit_id: "ed_3", ops: [{ op: "swap_part", instance_id: "u_mcu_l", part_id: "mod:xiao_ble" }] }).label).toBe("Swapped to mod:xiao_ble");
    expect(one("edit.applied", { edit_id: "ed_4", ops: [{ op: "remove_part", instance_id: "u_oled_l" }] })).toMatchObject({ action: "pick", label: "Removed a part" });
    const many = Array.from({ length: 6 }, (_, i) => ({ op: "move", instance_id: `u_${i}`, mode: "delta" }));
    expect(beatsFor(ev("edit.applied", { edit_id: "ed_5", ops: many }), build).length).toBeLessThanOrEqual(3);
    expect(beatsFor(ev("edit.applied", { edit_id: "ed_6" }), build)).toEqual([]);
  });

  it("looks worried at a rejected edit, with the reason", () => {
    const b = one("edit.rejected", {
      edit_id: "ed_1",
      msg_id: "m1",
      error: { code: "E_INCOMPATIBLE", message: "Kailh Choc v1 Red does not fit the left PCB's MX sockets.", retryable: false, subjects: [{ part_id: "sw:kailh_choc_red" }, { instance_id: "u_sw_l" }] },
    });
    expect(b).toMatchObject({ target: { kind: "part", id: "u_sw_l" }, action: "look", bad: true });
    expect(b.label).toMatch(/^Kailh Choc v1 Red/);
    expect(b.label.length).toBeLessThan(32);
    const vague = one("edit.rejected", { edit_id: "ed_2", error: { code: "E_INVALID_EDIT", message: "not available in mock mode", retryable: false } });
    expect(vague).toMatchObject({ target: { kind: "dom", key: "viewport" }, bad: true, label: "not available in mock mode" });
  });

  it("keeps every label on the chip", () => {
    const b = one("part.added", { part: bp("u_long", "p", "", "x".repeat(80), "module", "long") });
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
    ], 6);
    expect(q).toHaveLength(6);
    expect(ids(q)).toEqual(["p1", "d1", "s1", "p2", "p3", "p4"]);
    // Out of glances: the oldest real work goes next.
    expect(ids(enqueue(q, [mk("p5", "pick", "decision:d5"), mk("p6", "pick", "decision:d6")], 6))).toEqual(["d1", "p2", "p3", "p4", "p5", "p6"]);
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
    const many = Array.from({ length: 14 }, (_, i) => mk(`p${i}`, "pick", `decision:d${i}`));
    expect(QUEUE_MAX).toBe(6);
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
      ev("check.result", { results: [{ check_key: "slot.optional_missing:foam", rule_id: "r", status: "fail", severity: "error", message: "m", subjects: [] }] }),
      ev("build.done", {}),
    ];
    for (const e of stream) q = enqueue(q, beatsFor(e, build));
    expect(q.length).toBeLessThanOrEqual(QUEUE_MAX);
    expect(q[q.length - 1].action).toBe("cheer");
    // Minor steps added nothing: only drops, the failing check and the cheer remain.
    expect(q.every((b) => ["drop", "check", "cheer"].includes(b.action))).toBe(true);
    expect(q.some((b) => b.bad)).toBe(true);
  });

  it("never drops a beat that has a line to say", () => {
    const q = enqueue([mk("said", "look", "viewport", { say: "This is the controller" })], Array.from({ length: 12 }, (_, i) => mk(`l${i}`, "look", `stage:s${i}`)));
    expect(ids(q)).toContain("said");
  });
});

describe("director pacing", () => {
  it("gives full dwell to a short queue and hurries a long one, never below 60%", () => {
    const b = { dwellMs: 1000 };
    expect(paceFor(b, 0)).toBe(1000);
    expect(paceFor(b, 3)).toBe(1000);
    expect(paceFor(b, 4)).toBe(750);
    expect(paceFor(b, 6)).toBe(600);
    expect(paceFor(b, 10)).toBe(600);
    expect(paceFor(b, Infinity)).toBe(600);
  });
});
