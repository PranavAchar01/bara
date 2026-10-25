import { describe, expect, it } from "vitest";
import { markSpares, type SimInput } from "./inputMap";
import { charOf, isBackspace } from "./keymap";
import { controlLegend, inputForKey, keyName, zmkCodeOf } from "./physical";
import { typedText, type SimEvent } from "./remote";

function input(name: string, code: string | null, role: SimInput["role"] = "key", pos: [number, number, number] = [0, 0, 0]): SimInput {
  return { id: `u#${name}`, name, code, role, instanceId: "u", index: 0, pressKey: `u:${name}`, pos };
}

const typed = (text: string, seq: number): SimEvent => ({ seq, t_ms: seq, type: "typed", text }) as SimEvent;

describe("a computer key reaches the matching keyboard key", () => {
  it("names letters, digits and editing keys in ZMK terms", () => {
    expect(zmkCodeOf("KeyK")).toBe("K");
    expect(zmkCodeOf("Digit7")).toBe("N7");
    expect(zmkCodeOf("Enter")).toBe("RET");
    expect(zmkCodeOf("Backspace")).toBe("BSPC");
    expect(zmkCodeOf("Space")).toBe("SPACE");
  });

  it("finds the key bound to that code, and either Shift for a board with one", () => {
    const keys = [input("K", "K"), input("LSHFT", "LSHFT"), input("RET", "RET"), input("BSPC", "BSPC")];
    expect(inputForKey("KeyK", keys)?.name).toBe("K");
    expect(inputForKey("Enter", keys)?.name).toBe("RET");
    expect(inputForKey("Backspace", keys)?.name).toBe("BSPC");
    expect(inputForKey("ShiftRight", keys)?.name).toBe("LSHFT");
    expect(inputForKey("KeyQ", keys)).toBeNull();
  });
});

describe("what the keyboard types", () => {
  it("K is k, and k with Shift held is K", () => {
    expect(charOf("K", false)).toBe("k");
    expect(charOf("K", true)).toBe("K");
    expect(charOf("N1", true)).toBe("!");
  });

  it("Enter starts a new line and Backspace deletes", () => {
    expect(charOf("RET", false)).toBe("\n");
    expect(isBackspace("BSPC")).toBe(true);
    expect(typedText([typed("k", 1), typed("K", 2), typed("\n", 3), typed("j", 4), typed("\b", 5)])).toBe("kK\n");
  });

  it("keeps what was typed before and drops the oldest past the limit", () => {
    expect(typedText([typed("x", 1)], "ab")).toBe("abx");
    expect(typedText([typed("abcdef", 1)], "", 4)).toBe("cdef");
  });
});

describe("a handheld's playable controls", () => {
  it("leaves reset and boot off the overlay and keeps one of several Selects", () => {
    const inputs = [
      input("UP", null, "dpad", [-30, 0, 0]),
      input("A", null, "action", [30, 0, 0]),
      input("RESET", null, "system", [60, 40, 0]),
      input("BOOT", null, "system", [60, 44, 0]),
      { ...input("SELECT", null, "system", [-5, -20, 0]), id: "s1" },
      { ...input("SELECT", null, "system", [-60, 40, 0]), id: "s2" },
    ];
    markSpares(inputs);
    expect(inputs.filter((i) => i.spare).map((i) => i.id)).toEqual(["u#RESET", "u#BOOT", "s2"]);
    expect(inputForKey("Backspace", inputs)?.id).toBe("s1");
    expect(controlLegend(inputs).map((r) => r.control)).toEqual(["D-pad", "A", "Select"]);
  });

  it("prints keys the way a keyboard does", () => {
    expect(keyName("KeyX")).toBe("X");
    expect(keyName("Enter")).toBe("Enter");
    expect(keyName("ShiftRight")).toBe("Right Shift");
  });
});
