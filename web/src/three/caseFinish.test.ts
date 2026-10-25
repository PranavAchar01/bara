import { describe, expect, it } from "vitest";
import { caseMaterial, FINISHES, finishInfo, resolveFinish } from "./caseFinish";

describe("case finishes", () => {
  it("defaults to satin with the preset's own clarity and frost", () => {
    expect(resolveFinish(undefined)).toEqual({ preset: "satin", clarity: 0, frost: 0.5 });
    expect(resolveFinish({ preset: "clear" })).toEqual({ preset: "clear", clarity: 0.96, frost: 0.05 });
    expect(resolveFinish({ preset: "frosted", clarity: 0.4 }).clarity).toBe(0.4);
  });

  it("lets light through only the see-through finishes", () => {
    for (const f of FINISHES) {
      const m = caseMaterial("#7FB5E6", { preset: f.preset });
      expect(m.transmission > 0).toBe(f.seeThrough);
    }
    expect(caseMaterial("#7FB5E6", { preset: "frosted", clarity: 0.3 }).transmission).toBeCloseTo(0.3);
  });

  it("frost makes the surface rougher", () => {
    const polished = caseMaterial("#202326", { preset: "clear", frost: 0 });
    const frosted = caseMaterial("#202326", { preset: "clear", frost: 1 });
    expect(frosted.roughness).toBeGreaterThan(polished.roughness);
  });

  it("reuses one material per look, so sliders do not compile new shaders", () => {
    const a = caseMaterial("#202326", { preset: "smoke", clarity: 0.801 });
    const b = caseMaterial("#202326", { preset: "smoke", clarity: 0.799 });
    expect(a).toBe(b);
  });

  it("reports a spec material for every finish", () => {
    expect(finishInfo("metal").material).toBe("metal");
    expect(finishInfo("clear").material).toBe("glass");
    expect(finishInfo("unknown").preset).toBe("satin");
  });
});
