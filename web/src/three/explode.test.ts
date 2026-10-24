import { describe, expect, it } from "vitest";
import { LAYER_RANK, explodeZ, humanGroupName, layerGap, layerOf } from "./explode";
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
