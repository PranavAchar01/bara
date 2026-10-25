import { describe, expect, it } from "vitest";
import { unitsOf } from "./SimHotspots";
import type { RemoteInput } from "./remote";

const ax = (id: string): RemoteInput => ({ id, label: id, kind: "axis", instance_id: "j" });

describe("unitsOf", () => {
  it("gives each of two sticks its own hit box", () => {
    const u = unitsOf({ instanceId: "j", inputs: [ax("x0"), ax("y0"), ax("x1"), ax("y1")], poses: [[0, 0, 0], [30, 0, 0]] });
    expect(u).toHaveLength(2);
    expect(u[1].inputs.map((i) => i.id)).toEqual(["x1", "y1"]);
    expect(u[1].at).toEqual([30, 0, 0]);
  });
  it("keeps one stick as one box", () => {
    expect(unitsOf({ instanceId: "j", inputs: [ax("x0"), ax("y0")] })).toHaveLength(1);
  });
});
