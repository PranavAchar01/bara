import { describe, expect, it } from "vitest";
import { DRAG_PX, EXPLODE_SETTLE, LAYER_RANK, easeInOutCubic, explodeZ, isDrag, layerProgress, humanGroupName, layerGap, layerOf, layerOffsets, tiersByX } from "./explode";
import type { BuildPart } from "../spec/types";

const part = (part_id: string, kind: string, primary_function: string, display_name = part_id): Pick<BuildPart, "part_id" | "card" | "label"> => ({
  part_id,
  card: { part_id, display_name, kind, primary_function },
});

describe("exploded layers", () => {
  it("stacks the keyboard from the case floor up", () => {
    const order = [
      layerOf(part("bat:lipo", "component", "power.battery")),
      layerOf(part("pcb:corne_l", "pcb", "interconnect.pcb")),
      layerOf(part("mod:nice_nano_v2", "module", "compute.mcu")),
      layerOf(part("mech:corne_plate", "mechanical", "mech.plate")),
      layerOf(part("sw:gateron_yellow_mx", "component", "input.key")),
      layerOf(part("cap:dsa_1u_pbt", "mechanical", "mech.keycap")),
      layerOf(part("disp:ssd1306_128x32", "module", "display.oled")),
    ].map((l) => LAYER_RANK[l]);
    expect([...order].sort((a, b) => a - b)).toEqual(order);
    expect(new Set(order).size).toBe(order.length);
  });

  it("keeps the case floor still and moves upper layers by rank", () => {
    expect(explodeZ("case", 20, 1)).toBe(0);
    expect(explodeZ("keycaps", 20, 0.5)).toBe(LAYER_RANK.keycaps * 10);
    expect(layerGap(10)).toBe(12);
    expect(layerGap(1000)).toBe(48);
  });

  it("names parts for people, not by catalog id", () => {
    expect(humanGroupName(part("cap:dsa_1u_pbt", "mechanical", "mech.keycap"))).toBe("Keycaps");
    expect(humanGroupName(part("mod:nice_nano_v2", "module", "compute.mcu", "nice!nano v2"))).toBe("MCU");
    expect(humanGroupName(part("bat:lipo_301230_110", "component", "power.battery"))).toBe("Battery");
    expect(humanGroupName(part("conn:pj320a_trrs", "component", "interconnect.jack"))).toBe("Jack");
  });
});

describe("role names", () => {
  const slot = (p: ReturnType<typeof part>, label: string) => ({ ...p, label });
  it("uses the plan's slot label, not a keyword guess", () => {
    const led = slot(part("lcsc:kt_0603r_c2286", "component", "display.indicator_led", "KT-0603R"), "Player/status LEDs");
    expect(humanGroupName(led)).toBe("Player/status LEDs");
    expect(layerOf(led)).toBe("board_parts");
    const enc = slot(part("enc:alps_ec11e", "component", "input.rotary_encoder"), "Rotary encoder");
    const cap = slot(part("knob:knobby", "mechanical", "mech.knob"), "Thumbstick caps");
    expect(humanGroupName(enc)).not.toBe(humanGroupName(cap));
  });
  it("keeps a slide power switch off the key switch layer", () => {
    expect(layerOf(part("sw:power_msk12c02", "component", "power.switch"))).toBe("board_parts");
    expect(layerOf(part("sw:kailh_choc_red", "component", "input.key"))).toBe("switches");
  });
});

describe("layerOffsets", () => {
  it("stacks layers with clearance between the top of one and the bottom of the next", () => {
    const ext: Record<"case" | "pcb" | "switches" | "keycaps", [number, number]> = { case: [0, 12], pcb: [2, 4], switches: [3, 20], keycaps: [14, 24] };
    const off = layerOffsets(ext, 6);
    expect(off.case).toBe(0);
    // each layer's lifted bottom clears the lifted top of everything below it
    let top = -Infinity;
    for (const l of ["case", "pcb", "switches", "keycaps"] as const) {
      expect(ext[l][0] + off[l]!).toBeGreaterThanOrEqual(top + (top === -Infinity ? 0 : 6) - 1e-9);
      top = Math.max(top, ext[l][1] + off[l]!);
    }
  });
  it("never moves a layer below the one under it, and skips layers it has no extent for", () => {
    const off = layerOffsets({ pcb: [0, 2], plate: [50, 52], switches: [51, 60] }, 5);
    expect(off.plate).toBeGreaterThanOrEqual(off.pcb!);
    expect(off.switches).toBeGreaterThanOrEqual(off.plate!);
    expect("case" in off).toBe(false);
  });
  it("keeps keycaps over their switches: only z changes, and they clear the switch tops", () => {
    const off = layerOffsets({ switches: [0, 18], keycaps: [10, 22] }, 8);
    expect(10 + off.keycaps!).toBeGreaterThanOrEqual(18 + off.switches! + 8);
  });
});

describe("explode motion", () => {
  it("eases softly and meets both ends", () => {
    expect(easeInOutCubic(0)).toBe(0);
    expect(easeInOutCubic(1)).toBe(1);
    expect(easeInOutCubic(0.5)).toBeCloseTo(0.5);
    expect(easeInOutCubic(0.1)).toBeLessThan(0.1);
    expect(easeInOutCubic(0.9)).toBeGreaterThan(0.9);
  });

  it("starts from the top, lands the lowest layer last, and never lets a layer pass the one under it", () => {
    const top = LAYER_RANK.lid;
    for (let p = 0; p <= 1.0001; p += 0.02) {
      let prev = -Infinity;
      for (let rank = 0; rank <= top; rank++) {
        const v = layerProgress(p, rank, top, true);
        expect(v).toBeGreaterThanOrEqual(prev - 1e-9);
        prev = v;
      }
    }
    // a little way in only the top has moved
    expect(layerProgress(0.15, top, top, true)).toBeGreaterThan(0);
    expect(layerProgress(0.15, 1, top, true)).toBe(0);
    // every layer is at rest by the time the labels start to fade
    for (let rank = 0; rank <= top; rank++) expect(layerProgress(EXPLODE_SETTLE, rank, top, true)).toBeCloseTo(1);
  });

  it("agrees with the plain slider at both ends and follows it directly otherwise", () => {
    for (const rank of [0, 3, 8]) {
      expect(layerProgress(0, rank, 8, true)).toBe(0);
      expect(layerProgress(1, rank, 8, true)).toBe(1);
    }
    expect(layerProgress(0.37, 5, 8, false)).toBeCloseTo(0.37);
    expect(layerProgress(-1, 5, 8, false)).toBe(0);
    expect(layerProgress(2, 5, 8, false)).toBe(1);
  });
});

describe("press versus drag", () => {
  it("is a press until the pointer travels past a few px", () => {
    expect(isDrag(0, 0)).toBe(false);
    expect(isDrag(DRAG_PX, 0)).toBe(false);
    expect(isDrag(3, 3)).toBe(false);
    expect(isDrag(DRAG_PX + 1, 0)).toBe(true);
    expect(isDrag(-4, 4)).toBe(true);
    expect(isDrag(10, 0, 20)).toBe(false);
  });
});

describe("tiersByX", () => {
  it("staggers neighbouring small parts left to right and leaves whole layers flat", () => {
    const t = tiersByX("board_parts", [{ key: "c", x: 30 }, { key: "a", x: 0 }, { key: "b", x: 10 }, { key: "d", x: 40 }]);
    expect([t.get("a"), t.get("b"), t.get("c"), t.get("d")]).toEqual([0, 1, 2, 0]);
    expect(tiersByX("pcb", [{ key: "a", x: 0 }, { key: "b", x: 1 }]).size).toBe(0);
    expect(tiersByX("board_parts", [{ key: "a", x: 0 }]).size).toBe(0);
  });
});
