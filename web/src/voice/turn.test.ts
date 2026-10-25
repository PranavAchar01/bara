import { describe, expect, it } from "vitest";
import { cleanTranscript, endOfTurnMs } from "./turn";

describe("cleanTranscript", () => {
  it("drops fillers", () => {
    expect(cleanTranscript("um I want uh a macropad, uhh with a knob hmm")).toBe("I want a macropad, with a knob");
    expect(cleanTranscript("Umm, make it wireless")).toBe("Make it wireless");
  });
  it("drops stutters and false starts", () => {
    expect(cleanTranscript("a wi- wireless k-k-keyboard")).toBe("A wireless keyboard");
  });
  it("drops repeated words and phrases", () => {
    expect(cleanTranscript("I I want the the split keyboard")).toBe("I want the split keyboard");
    expect(cleanTranscript("I want I want a macropad")).toBe("I want a macropad");
  });
  it("leaves clean speech alone", () => {
    expect(cleanTranscript("What does the OLED connect to?")).toBe("What does the OLED connect to?");
    expect(cleanTranscript("an ergonomic keyboard")).toBe("An ergonomic keyboard");
    expect(cleanTranscript("")).toBe("");
    expect(cleanTranscript("uh um")).toBe("");
  });
});

describe("endOfTurnMs", () => {
  it("waits for something to be said", () => {
    expect(endOfTurnMs("")).toBeNull();
  });
  it("ends quickly after a finished sentence", () => {
    expect(endOfTurnMs("Build me a macropad.")!).toBeLessThan(endOfTurnMs("build me a macropad")!);
  });
  it("waits longer when the sentence is hanging", () => {
    expect(endOfTurnMs("a keyboard with")!).toBeGreaterThan(endOfTurnMs("a keyboard with an OLED")!);
    expect(endOfTurnMs("a keyboard um")!).toBeGreaterThan(endOfTurnMs("a keyboard with an OLED")!);
  });
});
