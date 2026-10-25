import { describe, expect, it } from "vitest";
import { sentences } from "./voice";

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
