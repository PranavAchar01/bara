import { describe, expect, it } from "vitest";
import { sentences, trimReply } from "./voice";

describe("sentences", () => {
  it("splits a reply so the first sentence can start alone", () => {
    expect(sentences("I found a keyboard matrix. Now routing the board. Want a mouse too?")).toEqual([
      "I found a keyboard matrix.",
      "Now routing the board.",
      "Want a mouse too?",
    ]);
  });
  it("keeps short pieces with a neighbour", () => {
    expect(sentences("Done. The board routed cleanly on two layers.")).toEqual(["Done. The board routed cleanly on two layers."]);
    expect(sentences("The board routed cleanly on two layers. Done.")).toEqual(["The board routed cleanly on two layers. Done."]);
  });
});

describe("trimReply", () => {
  it("keeps one or two short sentences", () => {
    expect(trimReply("Routing the board. Two layers. Then the case. Then checks.")).toBe("Routing the board. Two layers.");
    expect(trimReply("  Case closed.  ")).toBe("Case closed.");
  });
  it("never reads out a wall of words", () => {
    const long = `${"word ".repeat(80)}end.`;
    expect(trimReply(long).length).toBeLessThanOrEqual(200);
  });
});
