import { describe, expect, it } from "vitest";
import { clientNames, terminalLine } from "./remote";
import type { InputMap } from "./inputMap";

describe("simulator client", () => {
  it("keys the workspace's control names the way the engine keys inputs", () => {
    const map: InputMap = {
      mode: "game",
      source: "position",
      displays: [],
      inputs: [
        { id: "u_btn:0", name: "A", code: null, role: "action", instanceId: "u_btn", index: 0, pressKey: "u_btn:0", pos: [0, 0, 0] },
        { id: "u_sw:2", name: "Q", code: "Q", role: "key", instanceId: "u_sw", index: 2, pressKey: "k:2", pos: [0, 0, 0] },
      ],
    } as unknown as InputMap;
    expect(clientNames(map)).toEqual({ names: { "u_btn#0": "A", "u_sw#2": "Q" }, codes: { "u_sw#2": "Q" } });
    expect(clientNames(null)).toEqual({ names: {}, codes: {} });
  });

  it("writes one terminal line per event, in plain words", () => {
    expect(terminalLine({ seq: 1, t_ms: 1234, type: "serial", text: "press A button" })?.text).toBe("1.234s  press A button");
    expect(terminalLine({ seq: 2, t_ms: 0, type: "serial", text: "HID pad 01" })).toBeNull();
    expect(terminalLine({ seq: 3, t_ms: 0, type: "input", label: "Volume knob", turn: 1 })?.text).toContain("Volume knob turned clockwise");
    expect(terminalLine({ seq: 4, t_ms: 0, type: "gpio", pin: 25, level: 1 })).toBeNull();
  });
});
