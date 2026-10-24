import { describe, expect, it } from "vitest";
import type { Build, BuildPart, PartCard } from "../spec/types";
import { FALLBACK, parseAsk, pickSwap, resolveAsk, specNumber, type SwapOption } from "./ask";

const card = (part_id: string, display_name: string, specs: [string, string | number, string?][] = []): PartCard => ({
  part_id,
  display_name,
  kind: "module",
  key_specs: specs.map(([label, value, unit]) => ({ label, value, unit })),
});

const bat = (id: string, mah: number) => card(id, `LiPo ${mah} mAh`, [["Capacity", mah, "mAh"]]);

const inst = (instance_id: string, c: PartCard, slot_id: string | null = "s_power"): BuildPart => ({
  instance_id,
  part_id: c.part_id,
  slot_id,
  quantity: 1,
  placement: { mode: "single", position_mm: [0, 0, 0], rotation_deg: [0, 0, 0] },
  card: c,
});

const battery = inst("i_bat", bat("lipo_1000", 1000));
const mcu = inst("i_mcu", card("esp32c3", "ESP32-C3 Mini", [["Flash", "4 MB"]]), "s_mcu");

const build: Build = {
  build_id: "b1",
  prompt: "a remote",
  status: "done",
  revision: 3,
  tier: "compose",
  slots: [],
  decisions: [
    { decision_id: "d1", slot_id: "s_power", method: "model_pick", chosen_part_id: "lipo_1000", survivors: 3, reason: "Smallest cell that runs a day. It fits under the board." },
  ],
  parts: [battery, mcu],
  connections: [{ connection_id: "c1", type: "power", kind: "electrical", from: { instance_id: "i_bat", interface_id: "out" }, to: { instance_id: "i_mcu", interface_id: "vin" } }],
  enclosures: [{ enclosure_id: "e1", kind: "generated" } as Build["enclosures"][number]],
  boards: [],
  checks: [],
  warnings: [],
  last_seq: 10,
};

const options: SwapOption[] = [
  { card: bat("lipo_1000", 1000) },
  { card: bat("lipo_500", 500) },
  { card: bat("lipo_250", 250) },
  { card: bat("lipo_2000", 2000) },
  { card: bat("lipo_400_bad", 400), compatible: false },
];
const ctx = { build, instance: battery, options };

describe("parseAsk", () => {
  it("reads swaps", () => {
    expect(parseAsk("swap this for a smaller battery")).toEqual({ kind: "swap", want: "smaller", name: "battery" });
    expect(parseAsk("Can you use a bigger one?")).toMatchObject({ kind: "swap", want: "bigger" });
    expect(parseAsk("something cheaper")).toMatchObject({ kind: "swap", want: "cheaper" });
    expect(parseAsk("replace it with the ESP32-S3")).toEqual({ kind: "swap", want: "any", name: "esp32-s3" });
  });

  it("reads moves with units and several directions", () => {
    expect(parseAsk("move it 5mm left")).toEqual({ kind: "move", delta: [-5, 0, 0] });
    expect(parseAsk("shift 1 cm right and 2 mm up")).toEqual({ kind: "move", delta: [10, 0, 2] });
    expect(parseAsk("nudge it back a little")).toEqual({ kind: "move", delta: [0, 2, 0] });
    expect(parseAsk("raise it 3mm")).toEqual({ kind: "move", delta: [0, 0, 3] });
  });

  it("reads rotations", () => {
    expect(parseAsk("rotate 45 degrees")).toEqual({ kind: "rotate", deg: 45 });
    expect(parseAsk("rotate it clockwise")).toEqual({ kind: "rotate", deg: -90 });
    expect(parseAsk("flip it")).toEqual({ kind: "rotate", deg: 180 });
  });

  it("reads colours, for the part or the case", () => {
    expect(parseAsk("make the case red")).toMatchObject({ kind: "color", hex: "#C2362F", target: "case" });
    expect(parseAsk("paint it #0af")).toMatchObject({ kind: "color", hex: "#00AAFF", target: "part" });
    expect(parseAsk("make it black metal")).toMatchObject({ kind: "color", hex: "#202326", material: "metal" });
    expect(parseAsk("turn it blue")).toMatchObject({ kind: "color" });
  });

  it("reads removals", () => {
    expect(parseAsk("please remove this")).toEqual({ kind: "remove" });
    expect(parseAsk("get rid of it")).toEqual({ kind: "remove" });
  });

  it("reads questions by topic", () => {
    expect(parseAsk("why this one?")).toEqual({ kind: "question", topic: "why" });
    expect(parseAsk("why did you pick it")).toEqual({ kind: "question", topic: "why" });
    expect(parseAsk("what is this")).toEqual({ kind: "question", topic: "what" });
    expect(parseAsk("what does it connect to?")).toEqual({ kind: "question", topic: "connections" });
    expect(parseAsk("how big is it")).toEqual({ kind: "question", topic: "specs" });
    expect(parseAsk("what are the alternatives")).toEqual({ kind: "question", topic: "options" });
  });

  it("gives up on nonsense", () => {
    expect(parseAsk("banana")).toEqual({ kind: "unknown" });
    expect(parseAsk("   ")).toEqual({ kind: "unknown" });
  });
});

describe("specNumber", () => {
  it("reads numbers and volumes", () => {
    expect(specNumber(12)).toBe(12);
    expect(specNumber("1200 mAh")).toBe(1200);
    expect(specNumber("30 x 20 x 5 mm")).toBe(3000);
    expect(specNumber(true)).toBeNull();
  });
});

describe("pickSwap", () => {
  it("takes the nearest smaller or bigger compatible option", () => {
    expect(pickSwap(battery.card, options, "smaller", null).card?.part_id).toBe("lipo_500");
    expect(pickSwap(battery.card, options, "bigger", null).card?.part_id).toBe("lipo_2000");
  });
  it("matches by name", () => {
    expect(pickSwap(battery.card, options, "any", "250").card?.part_id).toBe("lipo_250");
  });
  it("says why when nothing fits", () => {
    const r = pickSwap(battery.card, [{ card: battery.card }], "smaller", null);
    expect(r.card).toBeNull();
    expect(r.why).toMatch(/no compatible/);
    expect(pickSwap(battery.card, options, "cheaper", null).card).toBeNull();
  });
});

describe("resolveAsk", () => {
  it("swaps to a smaller battery", () => {
    const r = resolveAsk(parseAsk("swap this for a smaller battery"), ctx);
    expect(r.kind).toBe("edit");
    if (r.kind !== "edit") return;
    expect(r.ops).toEqual([{ op: "swap_part", instance_id: "i_bat", part_id: "lipo_500" }]);
    expect(r.label).toBe("Swap to LiPo 500 mAh");
  });

  it("moves and rotates by delta", () => {
    const m = resolveAsk(parseAsk("move it 5mm left"), ctx);
    expect(m.kind === "edit" && m.ops[0]).toEqual({ op: "move", instance_id: "i_bat", position_mm: [-5, 0, 0], mode: "delta", lock: true });
    const r = resolveAsk(parseAsk("rotate 90"), ctx);
    expect(r.kind === "edit" && r.ops[0]).toEqual({ op: "move", instance_id: "i_bat", rotation_deg: [0, 0, 90], mode: "delta", lock: true });
  });

  it("recolours the case when asked", () => {
    const r = resolveAsk(parseAsk("make the case red"), ctx);
    expect(r.kind === "edit" && r.ops[0]).toEqual({ op: "recolor", enclosure_id: "e1", color: { hex: "#C2362F", material: "plastic" } });
  });

  it("removes", () => {
    const r = resolveAsk({ kind: "remove" }, ctx);
    expect(r.kind === "edit" && r.ops).toEqual([{ op: "remove_part", instance_id: "i_bat" }]);
  });

  it("answers why from the decision, short enough to say", () => {
    const r = resolveAsk(parseAsk("why this one?"), ctx);
    expect(r).toMatchObject({ kind: "answer", say: "Smallest cell that runs a day." });
    expect(r.kind === "answer" && r.reply).toContain("3 candidates left");
  });

  it("answers connections and specs", () => {
    expect(resolveAsk({ kind: "question", topic: "connections" }, ctx)).toMatchObject({ say: "Wired to ESP32-C3 Mini" });
    expect(resolveAsk({ kind: "question", topic: "specs" }, ctx)).toMatchObject({ say: "Capacity 1000 mAh" });
  });

  it("keeps every said line under 60 chars", () => {
    const long = { ...ctx, build: { ...build, decisions: [{ ...build.decisions![0], reason: "x ".repeat(80) }] } };
    const r = resolveAsk({ kind: "question", topic: "why" }, long);
    expect(r.kind === "answer" && r.say.length).toBeLessThanOrEqual(60);
  });

  it("falls back helpfully", () => {
    const r = resolveAsk(parseAsk("banana"), ctx);
    expect(r).toMatchObject({ kind: "answer", reply: FALLBACK });
  });
});
