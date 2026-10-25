import { describe, expect, it } from "vitest";
import { cleanTranscript, endOfTurnMs, isNoise, pickOption } from "./turn";

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

describe("pickOption", () => {
  const options = [
    { option_id: "a", label: "Wireless" },
    { option_id: "b", label: "USB cable" },
  ];
  it("matches by words or by place", () => {
    expect(pickOption("the wireless one please", options)).toBe("a");
    expect(pickOption("usb cable", options)).toBe("b");
    expect(pickOption("the second one", options)).toBe("b");
  });
  it("leaves anything else as free text", () => {
    expect(pickOption("make it glow in the dark", options)).toBeNull();
  });
});

describe("hardware words survive cleaning", () => {
  it("keeps millimetres", () => {
    expect(cleanTranscript("make the knob 12 mm wide")).toBe("Make the knob 12 mm wide");
    expect(cleanTranscript("mmm a 3 mm plate")).toBe("A 3 mm plate");
  });
});

describe("isNoise", () => {
  it("drops what speech-to-text makes up from a cough", () => {
    expect(isNoise("Thank you.", 200)).toBe(true);
    expect(isNoise("Thanks for watching!", 400)).toBe(true);
    expect(isNoise("", 2000)).toBe(true);
  });
  it("keeps real answers", () => {
    expect(isNoise("Okay", 300)).toBe(false);
    expect(isNoise("Yes", 250)).toBe(false);
    expect(isNoise("Thank you", 1500)).toBe(false);
    expect(isNoise("Build a keyboard", 900)).toBe(false);
  });
});
