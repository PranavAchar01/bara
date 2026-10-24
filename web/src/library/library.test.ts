import { describe, expect, it } from "vitest";
import { summarize } from "./library";
import { emptyView } from "../state/view";
import type { Build } from "../spec/types";

const build = (over: Partial<Build>): Build =>
  ({ build_id: "b", prompt: "a keyboard", status: "done", parts: [], decisions: [], revision: 0, warnings: [], ...over }) as unknown as Build;

describe("library card summary", () => {
  it("names the reused design and counts every piece", () => {
    const view = { ...emptyView(), reuse: { tier: "exact", design_id: "corne", design: { name: "Corne (crkbd)" }, considered: [], unmet_hard: [], reason: "" } } as never;
    const b = build({ parts: [{ quantity: 42 }, { quantity: 1 }] as never });
    expect(summarize(b, view)).toBe("Corne (crkbd) · 43 parts");
  });

  it("falls back to the kind of device, and says nothing it doesn't know", () => {
    expect(summarize(build({ spec: { device_class: "input_device" } as never, parts: [{ quantity: 3 }] as never }), emptyView())).toBe("Input device · 3 parts");
    expect(summarize(build({}), emptyView())).toBe("");
  });
});
