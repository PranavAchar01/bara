import { describe, expect, it } from "vitest";
import { unpackFb } from "./screenDraw";
import { typedText, terminalLine, type SimEvent } from "./remote";
import { simHooks, useSim, pressInput } from "./simStore";
import { createRuntime } from "./runtime";

const ev = (seq: number, text: string): SimEvent => ({ seq, t_ms: seq, type: "typed", text });

describe("device-first screen helpers", () => {
  it("unpacks four pixels a byte, low bits first", () => {
    const b64 = Buffer.from([0b11100100, 0b00000001]).toString("base64");
    expect([...unpackFb(b64, 5, 1)]).toEqual([0, 1, 2, 3, 1]);
  });

  it("builds typed text with backspace and keeps earlier text", () => {
    const first = typedText([ev(1, "k"), ev(2, "x"), ev(3, "\b")]);
    expect(first).toBe("k");
    expect(typedText([ev(4, "e"), ev(5, "y")], first)).toBe("key");
  });

  it("leaves typed events out of the raw log (the report line carries them)", () => {
    expect(terminalLine(ev(1, "k"))).toBeNull();
  });

  it("sends a press on the 3D model to the engine hook", () => {
    const input = { id: "a", name: "A", code: null, role: "action", instanceId: "btn", index: 0, pressKey: "btn:0", pos: [0, 0, 0] } as never;
    const map = { mode: "pad", inputs: [input], source: "position", displays: [] } as never;
    useSim.setState({ map, runtime: createRuntime(map) });
    const seen: string[] = [];
    simHooks.press = (i) => seen.push(i.instanceId);
    pressInput(input);
    simHooks.press = undefined;
    expect(seen).toEqual(["btn"]);
    expect(useSim.getState().runtime?.terminal.text).toBe("");
  });
});
