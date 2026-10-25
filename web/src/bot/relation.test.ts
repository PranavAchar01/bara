import { describe, expect, it } from "vitest";
import { relation } from "./relation";

describe("relation", () => {
  it("reads a thing beside the build as a device of its own", () => {
    for (const p of ["add a mouse next to it", "a trackball to go with this", "build a numpad beside the keyboard"]) {
      expect(relation(p)?.kind, p).toBe("companion");
    }
    expect(relation("add a mouse next to it")).toEqual({ kind: "companion", thing: "mouse", prompt: "a mouse" });
  });

  it("reads a device added, connected or matched to the build as a device of its own", () => {
    for (const p of [
      "add a mouse to this keyboard",
      "I want to add a mouse to the keyboard",
      "connect a mouse",
      "I want to connect this keyboard to a mouse",
      "pair this with a numpad",
      "make a matching mouse",
    ]) {
      expect(relation(p), p).toMatchObject({ kind: "companion" });
    }
    expect(relation("I want to connect this keyboard to a mouse")?.thing).toBe("mouse");
  });

  it("reads a thing put on or added to the build as a part for it", () => {
    expect(relation("add a knob to it")).toMatchObject({ kind: "modify", thing: "knob" });
    expect(relation("put an OLED screen on the keyboard")).toMatchObject({ kind: "modify", thing: "oled screen" });
  });

  it("leaves other lines alone", () => {
    expect(relation("a gameboy")).toBeNull();
    expect(relation("make the keycaps blue")).toBeNull();
    expect(relation("connect this keyboard to the wifi")).toBeNull();
  });
});
