import { describe, expect, it } from "vitest";
import type { Surface, SurfaceControl } from "./remote";
import { applyOps, cleanName, emptyLayout, groupRows, move, resolveRows, sanitize, setHidden, withUnit } from "./surface";

const ctl = (id: string, extra: Partial<SurfaceControl> = {}): SurfaceControl => ({
  input_id: id,
  kind: "button",
  control: "button",
  label: id,
  unit: "",
  group: "Controls",
  ...extra,
});
const surface: Surface = {
  controls: [
    ctl("a"),
    ctl("b"),
    ctl("soil", { kind: "sensor", control: "slider", label: "Soil volumetric water content", unit: "%", group: "Measurements", min: 0, max: 100, default: 40 }),
  ],
  outputs: [],
  lead: "b",
  sig: "x",
  by: "parts",
};

describe("play surface layout", () => {
  it("puts the lead control first until the person orders them", () => {
    expect(resolveRows(surface, emptyLayout()).map((r) => r.input_id)).toEqual(["b", "a", "soil"]);
  });
  it("hides, renames and reorders without dropping the control", () => {
    let l = setHidden(emptyLayout(), "a", true);
    l = move(l, surface, "soil", -1);
    const rows = resolveRows(surface, { ...l, names: { b: "Start / stop" } });
    expect(rows.find((r) => r.input_id === "a")?.hidden).toBe(true);
    expect(rows.find((r) => r.input_id === "b")?.label).toBe("Start / stop");
    expect(rows.map((r) => r.input_id)).toEqual(["b", "soil", "a"]);
  });
  it("ignores ids that are not controls of this device", () => {
    const l = sanitize({ hidden: ["ghost", "a"], order: ["ghost"], names: { ghost: "x", a: "A key" }, lead: "ghost", values: { soil: 900, a: 3 } }, surface);
    expect(l.hidden).toEqual(["a"]);
    expect(l.order).toEqual([]);
    expect(l.names).toEqual({ a: "A key" });
    expect(l.lead).toBeNull();
    expect(l.values).toEqual({ soil: 100 });
  });
  it("agent changes are bounded by the real controls and ranges", () => {
    const out = applyOps(emptyLayout(), surface, [
      { op: "hide", input_id: "a" },
      { op: "hide", input_id: "ghost" },
      { op: "set", input_id: "soil", value: -5 },
      { op: "set", input_id: "a", value: 1 },
      { op: "rename", input_id: "b", label: "Select — first" },
    ]);
    expect(out.layout.hidden).toEqual(["a"]);
    expect(out.sensorSets).toEqual([{ id: "soil", value: 0 }]);
    expect(out.layout.names.b).toBe("Select, first");
  });
  it("groups in order of appearance and formats values with units", () => {
    expect(groupRows(resolveRows(surface, emptyLayout())).map((g) => g.group)).toEqual(["Controls", "Measurements"]);
    expect(withUnit(surface.controls[2], 42)).toBe("42 %");
    expect(cleanName("  A–B  ")).toBe("A,B");
  });
});
