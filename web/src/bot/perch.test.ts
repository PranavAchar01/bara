import { describe, expect, it } from "vitest";
import { clearOf, perch } from "./AgentStage";

const W = 1440;
const H = 900;
// every panel open: the strip, parts on the left, details on the right, the prompt at the bottom
const PANELS = [
  { x: 0, y: 0, w: W, h: 48 },
  { x: 12, y: 58, w: 300, h: 830 },
  { x: 1088, y: 58, w: 340, h: 830 },
  { x: 440, y: 828, w: 560, h: 50 },
];

describe("agent perch", () => {
  it("never lands on a panel, whatever the target", () => {
    const targets = [
      { x: 600, y: 400, w: 60, h: 40 }, // a part mid canvas
      { x: 330, y: 300, w: 40, h: 40 }, // a part against the parts panel
      { x: 1040, y: 120, w: 40, h: 40 }, // a part against the details panel, top
      { x: 40, y: 280, w: 240, h: 24 }, // a row inside the parts panel
      { x: 1100, y: 500, w: 300, h: 30 }, // something inside the details panel
      { x: 312, y: 48, w: 776, h: 852 }, // the whole canvas
    ];
    for (const t of targets) {
      const p = perch(t, 700, PANELS, W, H);
      expect(clearOf(p.x, p.y, PANELS, 22, 0)).toBe(true);
    }
  });
  it("sits right beside a free target", () => {
    const p = perch({ x: 600, y: 400, w: 60, h: 40 }, 0, PANELS, W, H);
    expect(Math.abs(p.x - (600 - 14 - 22))).toBeLessThan(1);
  });
});
