import { describe, expect, it } from "vitest";
import { splitSides, spreadLabels } from "./labels";

describe("spreadLabels", () => {
  it("keeps labels level with spread-out anchors", () => {
    expect(spreadLabels([100, 200, 300], 0, 1000, 40)).toEqual([100, 200, 300]);
  });
  it("pushes crowded labels apart by the gap, in order", () => {
    const ys = spreadLabels([100, 105, 110], 0, 1000, 40);
    expect(ys[1] - ys[0]).toBeGreaterThanOrEqual(40);
    expect(ys[2] - ys[1]).toBeGreaterThanOrEqual(40);
  });
  it("stays inside the band, shrinking the gap when it must", () => {
    const ys = spreadLabels([0, 0, 0, 0, 0], 100, 200, 40);
    expect(ys[0]).toBeGreaterThanOrEqual(100);
    expect(ys[4]).toBeLessThanOrEqual(200 + 1e-9);
    expect(ys[1] - ys[0]).toBeCloseTo(25);
  });
  it("pulls a run near the bottom back up", () => {
    const ys = spreadLabels([390, 395, 399], 0, 400, 40);
    expect(ys[2]).toBeLessThanOrEqual(400);
    expect(ys[2] - ys[1]).toBeGreaterThanOrEqual(40);
  });
});

describe("untangle", () => {
  it("swaps two leader lines that cross", async () => {
    const { untangle } = await import("./labels");
    // b sits just above a's line near the column, so b's drop to the lower slot cuts across a's line
    const pts = [{ k: "a", x: 0, y: 50 }, { k: "b", x: 200, y: 40 }];
    untangle(pts, [60, 140], 300);
    expect(pts.map((p) => p.k)).toEqual(["b", "a"]);
  });
  it("leaves lines that do not cross alone", async () => {
    const { untangle } = await import("./labels");
    const pts = [{ k: "a", x: 0, y: 100 }, { k: "b", x: 0, y: 200 }];
    untangle(pts, [100, 200], 300);
    expect(pts.map((p) => p.k)).toEqual(["a", "b"]);
  });
});

describe("splitSides", () => {
  const at = (key: string, x: number) => ({ key, x });
  it("puts each label on its own side of the model so lines never run back across it", () => {
    const left = splitSides([at("a", 10), at("b", 20), at("c", 30), at("d", 90), at("e", 95)], 50, 10);
    expect([...left].sort()).toEqual(["a", "b", "c"]);
  });
  it("moves only the parts nearest the middle when a column is full", () => {
    const left = splitSides([at("a", 10), at("b", 20), at("c", 30), at("d", 45), at("e", 90)], 50, 3);
    expect([...left].sort()).toEqual(["a", "b", "c"]);
  });
});
