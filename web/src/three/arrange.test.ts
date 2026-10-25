import { describe, expect, it } from "vitest";
import { arrangeDevices, chooseCamera, gapBetween, planScene, unionBox, type Box } from "./arrange";

const box = (w: number, d: number, h: number, at: [number, number, number] = [0, 0, 0]): Box => ({
  min: [at[0] - w / 2, at[1] - d / 2, at[2]],
  max: [at[0] + w / 2, at[1] + d / 2, at[2] + h],
});

const keyboard = box(355, 130, 38);
const mouse = box(62, 105, 38);
const lamp = box(90, 90, 240);
const pad = box(150, 100, 55);

describe("arrangeDevices", () => {
  it("stands a mouse to the right of a keyboard, a gap apart, centred front to back, on the floor", () => {
    const plan = planScene([mouse, keyboard]);
    const [m, k] = plan.placed;
    expect(m.min[0]).toBeGreaterThan(k.max[0]);
    const gap = m.min[0] - k.max[0];
    expect(gap).toBeCloseTo(gapBetween(keyboard, mouse), 5);
    expect((m.min[1] + m.max[1]) / 2).toBeCloseTo((k.min[1] + k.max[1]) / 2, 5);
    expect(m.min[2]).toBe(0);
    expect(k.min[2]).toBe(0);
  });

  it("does not depend on the order the devices are given in", () => {
    const a = planScene([keyboard, mouse]).placed;
    const b = planScene([mouse, keyboard]).placed;
    expect(b[1]).toEqual(a[0]);
    expect(b[0]).toEqual(a[1]);
  });

  it("scales the gap with the smaller device and keeps it within limits", () => {
    expect(gapBetween(keyboard, mouse)).toBeGreaterThan(gapBetween(keyboard, box(20, 20, 10)));
    expect(gapBetween(keyboard, keyboard)).toBe(65);
    expect(gapBetween(box(1000, 1000, 5), box(1000, 1000, 5))).toBe(80);
    expect(gapBetween(box(2, 2, 2), box(2, 2, 2))).toBe(12);
  });

  it("is centred on the origin and wraps a long row toward the front", () => {
    const boxes = [keyboard, pad, pad, pad, pad];
    const placed = arrangeDevices(boxes).map((o, i) => ({ min: boxes[i].min.map((v, j) => v + o[j]), max: boxes[i].max.map((v, j) => v + o[j]) }) as Box);
    const u = unionBox(placed);
    expect((u.min[0] + u.max[0]) / 2).toBeCloseTo(0, 5);
    const ys = new Set(placed.map((b) => Math.round(b.min[1])));
    expect(ys.size).toBeGreaterThan(1);
    expect(ys.size).toBeLessThan(boxes.length);
    // no two devices overlap on the floor
    for (let i = 0; i < placed.length; i++)
      for (let j = i + 1; j < placed.length; j++) {
        const a = placed[i];
        const b = placed[j];
        const apart = a.max[0] <= b.min[0] || b.max[0] <= a.min[0] || a.max[1] <= b.min[1] || b.max[1] <= a.min[1];
        expect(apart).toBe(true);
      }
  });
});

describe("chooseCamera", () => {
  it("goes high, near top-down, for a flat wide device, looking along its short axis", () => {
    const c = chooseCamera([keyboard]);
    expect(c.elevationDeg).toBeGreaterThan(65);
    expect(c.across).toBe("x");
    expect(Math.abs(c.dir[0])).toBeLessThan(0.05);
    expect(c.dir[1]).toBeLessThan(0);
    expect(c.dir[2]).toBeGreaterThan(0.9);
  });

  it("keeps a keyboard with a mouse beside it flat and high", () => {
    const c = planScene([keyboard, mouse]).camera;
    expect(c.elevationDeg).toBeGreaterThan(60);
    expect(c.across).toBe("x");
  });

  it("settles at a 3/4 view for tall and for handheld devices", () => {
    expect(chooseCamera([lamp]).elevationDeg).toBeLessThan(45);
    expect(chooseCamera([lamp]).yawDeg).toBeGreaterThan(20);
    const hand = chooseCamera([pad]).elevationDeg;
    expect(hand).toBeLessThan(chooseCamera([keyboard]).elevationDeg);
    expect(hand).toBeGreaterThan(chooseCamera([lamp]).elevationDeg);
  });

  it("turns so the long footprint axis runs across the screen", () => {
    const deep = box(80, 300, 30);
    const c = chooseCamera([deep]);
    expect(c.across).toBe("y");
    expect(c.dir[0]).toBeLessThan(-0.1);
    expect(Math.abs(c.dir[1])).toBeLessThan(Math.abs(c.dir[0]));
  });

  it("returns a unit direction", () => {
    for (const b of [keyboard, mouse, lamp, pad]) {
      const [x, y, z] = chooseCamera([b]).dir;
      expect(Math.hypot(x, y, z)).toBeCloseTo(1, 6);
    }
  });
});
