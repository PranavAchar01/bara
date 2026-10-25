import { describe, expect, it } from "vitest";
import { LAYER_RANK, explodeZ, humanGroupName, layerGap, layerOf, layerOffsets } from "./explode";
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
