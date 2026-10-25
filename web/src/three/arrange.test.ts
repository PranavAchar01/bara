import { describe, expect, it } from "vitest";
import { arrangeDevices, chooseCamera, deviceKind, gapBetween, layoutCamera, planLayout, planScene, unionBox, type Box } from "./arrange";

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

  it("returns a unit direction for every rule", () => {
    for (const k of ["keyboard", "macropad", "mouse", "handheld", "board", "other"] as const) {
      const [x, y, z] = layoutCamera([pad], [k]).dir;
      expect(Math.hypot(x, y, z)).toBeCloseTo(1, 6);
    }
  });

  it("returns a unit direction", () => {
    for (const b of [keyboard, mouse, lamp, pad]) {
      const [x, y, z] = chooseCamera([b]).dir;
      expect(Math.hypot(x, y, z)).toBeCloseTo(1, 6);
    }
  });
});

describe("deviceKind", () => {
  it("reads the kind from the spec taxonomy first, then the prompt", () => {
    expect(deviceKind({ taxonomy: ["input_device", "keyboard", "unibody"], prompt: "a keyboard" })).toBe("keyboard");
    expect(deviceKind({ taxonomy: ["input_device", "keyboard", "macropad"] })).toBe("macropad");
    expect(deviceKind({ taxonomy: ["handheld"], prompt: "a handheld game console like a game boy" })).toBe("handheld");
    expect(deviceKind({ prompt: "a wireless mouse with a scroll wheel" })).toBe("mouse");
    expect(deviceKind({ prompt: "create a stream deck with 4 buttons" })).toBe("macropad");
    expect(deviceKind({ prompt: "small desktop status display panel" })).toBe("board");
    // a keyboard with a trackball on it is still a keyboard, never a mouse
    expect(deviceKind({ taxonomy: ["input_device", "keyboard", "split"], prompt: "split keyboard, red trackball on the right" })).toBe("keyboard");
    expect(deviceKind({ prompt: "a plant monitor" })).toBe("board");
    expect(deviceKind({ prompt: "a rover" })).toBe("other");
    expect(deviceKind({})).toBe("other");
  });
});

describe("planLayout (camera layout by device kind)", () => {
  const handheld = box(90, 150, 32);
  const macropad = box(140, 130, 25);
  const centreX = (b: Box) => (b.min[0] + b.max[0]) / 2;

  it("puts the keyboard on the left and the mouse on the right at desk spacing, whatever the input order", () => {
    for (const devices of [
      [{ box: mouse, kind: "mouse" as const }, { box: keyboard, kind: "keyboard" as const }],
      [{ box: keyboard, kind: "keyboard" as const }, { box: mouse, kind: "mouse" as const }],
    ]) {
      const plan = planLayout(devices);
      const k = plan.placed[devices.findIndex((d) => d.kind === "keyboard")];
      const m = plan.placed[devices.findIndex((d) => d.kind === "mouse")];
      expect(m.min[0]).toBeGreaterThan(k.max[0]);
      const gap = m.min[0] - k.max[0];
      expect(gap).toBeGreaterThanOrEqual(50);
      expect(gap).toBeLessThanOrEqual(80);
      // centred together on the origin, both on the floor, centres in line front to back
      expect((Math.min(k.min[0], m.min[0]) + Math.max(k.max[0], m.max[0])) / 2).toBeCloseTo(0, 5);
      expect((m.min[1] + m.max[1]) / 2).toBeCloseTo((k.min[1] + k.max[1]) / 2, 5);
      expect(k.min[2]).toBe(0);
      expect(m.min[2]).toBe(0);
    }
  });

  it("keeps the mouse on the right even beside something bigger than the keyboard", () => {
    const big = box(400, 300, 20);
    const plan = planLayout([
      { box: mouse, kind: "mouse" },
      { box: big, kind: "board" },
      { box: keyboard, kind: "keyboard" },
    ]);
    const xs = plan.placed.map(centreX);
    expect(xs[2]).toBeLessThan(xs[1]); // keyboard before the board
    expect(Math.max(...xs)).toBe(xs[0]); // the mouse last
  });

  it("frames a keyboard and a mouse from one high front view, the row across the screen", () => {
    const c = planLayout([
      { box: keyboard, kind: "keyboard" },
      { box: mouse, kind: "mouse" },
    ]).camera;
    expect(c.across).toBe("x");
    expect(c.elevationDeg).toBeGreaterThanOrEqual(55);
    expect(c.elevationDeg).toBeLessThan(80);
    // in front of the desk (looking toward +y), not from the side
    expect(c.dir[1]).toBeLessThan(0);
    expect(Math.abs(c.dir[0])).toBeLessThan(Math.abs(c.dir[1]));
  });

  it("gives flat devices on their own a high or near top-down view", () => {
    for (const [b, k] of [
      [keyboard, "keyboard"],
      [macropad, "macropad"],
      [mouse, "mouse"],
      [box(60, 40, 6), "board"],
    ] as const) {
      const c = planLayout([{ box: b, kind: k }]).camera;
      expect(c.elevationDeg).toBeGreaterThanOrEqual(55);
      expect(c.across).toBe("x");
    }
    expect(planLayout([{ box: box(60, 40, 6), kind: "board" }]).camera.elevationDeg).toBeGreaterThan(70);
  });

  it("shows a handheld from the front at a 3/4, upright, never turned on its side", () => {
    const c = planLayout([{ box: handheld, kind: "handheld" }]).camera;
    // a tall portrait handheld would turn sideways under the size rule; by kind it stays upright
    expect(chooseCamera([handheld]).across).toBe("y");
    expect(c.across).toBe("x");
    expect(c.elevationDeg).toBeGreaterThan(35);
    expect(c.elevationDeg).toBeLessThan(60);
    expect(c.yawDeg).toBeGreaterThan(10);
    expect(c.dir[1]).toBeLessThan(-0.4);
    expect(c.elevationDeg).toBeLessThan(planLayout([{ box: keyboard, kind: "keyboard" }]).camera.elevationDeg);
  });

  it("drops lower for a desk that also holds a handheld, so the taller piece still reads", () => {
    const desk = planLayout([
      { box: keyboard, kind: "keyboard" },
      { box: mouse, kind: "mouse" },
    ]).camera;
    const mixed = planLayout([
      { box: keyboard, kind: "keyboard" },
      { box: handheld, kind: "handheld" },
    ]);
    expect(mixed.camera.elevationDeg).toBeLessThan(desk.elevationDeg);
    expect(mixed.camera.across).toBe("x");
    expect(centreX(mixed.placed[0])).toBeLessThan(centreX(mixed.placed[1]));
  });

  it("falls back to the size rule when no kind is known", () => {
    const plain = planScene([keyboard, mouse]);
    const unknown = planLayout([{ box: keyboard }, { box: mouse, kind: "other" }]);
    expect(unknown.camera).toEqual(plain.camera);
    expect(unknown.offsets).toEqual(plain.offsets);
  });

  it("never stands two devices on top of each other", () => {
    const devices = [
      { box: keyboard, kind: "keyboard" as const },
      { box: mouse, kind: "mouse" as const },
      { box: handheld, kind: "handheld" as const },
      { box: macropad, kind: "macropad" as const },
    ];
    const placed = planLayout(devices).placed;
    for (let i = 0; i < placed.length; i++)
      for (let j = i + 1; j < placed.length; j++) {
        const a = placed[i];
        const b = placed[j];
        expect(a.max[0] <= b.min[0] || b.max[0] <= a.min[0] || a.max[1] <= b.min[1] || b.max[1] <= a.min[1]).toBe(true);
      }
  });
});
