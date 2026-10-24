import { describe, expect, it } from "vitest";
import { charOf, isBackspace, keyCodes, keyLabel, parseKeymap } from "./keymap";

const KEYMAP = `
/ {
  keymap {
    compatible = "zmk,keymap";
    base {
      // base layer
      bindings = <
        &kp Q &kp W  &kp N1
        &kp SPACE &mo 1 &trans
        &kp BSPC &kp RET
      >;
    };
    upper { bindings = <&kp Z>; };
  };
};
`;

describe("parseKeymap", () => {
  it("reads the first bindings block in order", () => {
    const b = parseKeymap(KEYMAP);
    expect(b.map((x) => x.behavior)).toEqual(["kp", "kp", "kp", "kp", "mo", "trans", "kp", "kp"]);
    expect(b[4].param).toBe("1");
    expect(b[5].param).toBeNull();
  });
  it("keeps only &kp codes, null for the rest", () => {
    expect(keyCodes(parseKeymap(KEYMAP))).toEqual(["Q", "W", "N1", "SPACE", null, null, "BSPC", "RET"]);
  });
  it("returns nothing for a file without bindings", () => {
    expect(parseKeymap("/ { };")).toEqual([]);
  });
});

describe("charOf", () => {
  it("types letters, digits and punctuation, shifted or not", () => {
    expect(charOf("K", false)).toBe("k");
    expect(charOf("K", true)).toBe("K");
    expect(charOf("N1", false)).toBe("1");
    expect(charOf("N1", true)).toBe("!");
    expect(charOf("SEMI", false)).toBe(";");
    expect(charOf("SEMI", true)).toBe(":");
    expect(charOf("SPACE", false)).toBe(" ");
    expect(charOf("RET", false)).toBe("\n");
  });
  it("has no character for modifiers", () => {
    expect(charOf("LSHFT", false)).toBeNull();
  });
  it("knows backspace and labels", () => {
    expect(isBackspace("BSPC")).toBe(true);
    expect(isBackspace("Q")).toBe(false);
    expect(keyLabel("N7")).toBe("7");
    expect(keyLabel("BSPC")).toBe("BSPC");
  });
});
