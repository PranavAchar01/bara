import { describe, expect, it } from "vitest";
import type { Build } from "../spec/types";
import { deviceNoun, emptyScreen, foldScreen, planCombined, type SceneDevice } from "./combined";
import type { SimEvent } from "./remote";

function build(id: string, parts: [string, number, string?][]): Build {
  return {
    build_id: id,
    status: "done",
    parts: parts.map(([f, q, label], i) => ({ instance_id: `${id}_${i}`, quantity: q, label: label ?? null, card: { primary_function: f, display_name: label ?? f } })),
  } as unknown as Build;
}

const macropad: SceneDevice = {
  canvasId: "c1",
  name: "4-key USB macropad for streaming controls",
  build: build("b_m", [["compute.mcu", 1], ["input.key", 4], ["input.rotary_encoder", 1]]),
};
const display: SceneDevice = {
  canvasId: "c2",
  name: "small desktop status display panel",
  build: build("b_d", [["compute.mcu", 1], ["display.tft", 1, "3.5 in TFT"], ["display.indicator_led", 1], ["input.button", 2, "BOOT and RESET switches"]]),
};

describe("combined device", () => {
  it("names each device in a word or two", () => {
    expect(deviceNoun(macropad.name)).toBe("macropad");
    expect(deviceNoun(display.name)).toBe("desktop display");
    expect(deviceNoun("a wireless mouse that pairs over Bluetooth with a keyboard")).toBe("mouse");
  });

  it("runs the macropad and shows its keys and knob on the display, whichever tab it was opened on", () => {
    for (const order of [[macropad, display], [display, macropad]]) {
      const plan = planCombined("Macropad with desktop display", order, "a USB-C cable");
      expect(plan).not.toBeNull();
      expect(plan!.devices[plan!.source].noun).toBe("macropad");
      expect(plan!.devices[plan!.display!].noun).toBe("desktop display");
      expect(plan!.flows.map((f) => f.kind)).toEqual(["type", "knob"]);
      expect(plan!.testing).toBe(
        "Testing the macropad with desktop display, linked by a USB-C cable: keys typed on the macropad show on the desktop display and the macropad's knob changes what the desktop display shows.",
      );
    }
  });

  it("a keyboard and a mouse feed one computer", () => {
    const kb: SceneDevice = { canvasId: "c1", name: "low-profile keyboard", build: build("b_k", [["compute.mcu", 1], ["input.key", 61]]) };
    const mouse: SceneDevice = { canvasId: "c2", name: "wireless mouse", build: build("b_x", [["compute.mcu", 1], ["input.button", 2, "Left and right click"]]) };
    const plan = planCombined("Keyboard with mouse", [kb, mouse])!;
    expect(plan.display).toBeNull();
    expect(plan.flows.map((f) => f.text)).toEqual(["keys typed on the keyboard reach the same computer", "clicks and moves on the mouse reach the same computer"]);
  });

  it("one device alone is not a combined device", () => {
    expect(planCombined("x", [macropad])).toBeNull();
  });

  it("folds what the firmware did into the display's screen", () => {
    const ev = (e: Partial<SimEvent>): SimEvent => ({ seq: 1, t_ms: 0, type: "typed", ...e }) as SimEvent;
    let s = foldScreen(emptyScreen(), [ev({ text: "hi" }), ev({ text: "\b" }), ev({ text: "ey" })]);
    expect(s.text).toBe("hey");
    s = foldScreen(s, [ev({ type: "input", label: "Volume knob", turn: 1 }), ev({ type: "input", label: "Volume knob", turn: 1 })]);
    expect(s.level).toBe(60);
    expect(s.levelLabel).toBe("Volume");
    s = foldScreen(s, [ev({ type: "input", label: "Q key", down: true })]);
    expect(s.last).toBe("Q key pressed");
    expect(s.presses).toBe(1);
  });
});
