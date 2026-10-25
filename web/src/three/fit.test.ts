import { describe, expect, it } from "vitest";
import * as THREE from "three";
import { caseOverhang, sceneFill, sizedFill } from "./Viewport3D";

const box = (x0: number, y0: number, x1: number, y1: number) => new THREE.Box3(new THREE.Vector3(x0, y0, 0), new THREE.Vector3(x1, y1, 10));

describe("caseOverhang", () => {
  it("is 0 when the board sits inside the case", () => {
    expect(caseOverhang([box(-60, -40, 60, 40)], [box(-50, -30, 50, 30)])).toBe(0);
  });
  it("measures how far a shifted board pokes out", () => {
    expect(caseOverhang([box(-60, -40, 60, 40)], [box(-20, 10, 20, 52)])).toBe(12);
  });
  it("matches each half of a split to its own case", () => {
    const cases = [box(-150, -40, -10, 40), box(10, -40, 150, 40)];
    expect(caseOverhang(cases, [box(-140, -30, -20, 30), box(20, -30, 140, 30)])).toBe(0);
  });
  it("counts a board that touches no case as its whole size", () => {
    expect(caseOverhang([box(0, 0, 10, 10)], [box(100, 100, 130, 120)])).toBe(30);
  });
});

describe("sizedFill", () => {
  const dev = (w: number, h: number, d: number) => new THREE.Box3(new THREE.Vector3(0, 0, 0), new THREE.Vector3(w, h, d));
  it("gives a full-size keyboard the whole fill and a handheld less", () => {
    expect(sizedFill(dev(310, 110, 30), 0.5)).toBeCloseTo(0.5, 2);
    const handheld = sizedFill(dev(90, 148, 32), 0.5);
    expect(handheld).toBeLessThan(0.4);
    expect(handheld).toBeGreaterThan(0.3);
  });
  it("never shrinks a tiny part below 55% of the fill", () => {
    expect(sizedFill(dev(10, 10, 5), 0.5)).toBeCloseTo(0.275, 3);
  });
});

describe("sceneFill", () => {
  const dev = (w: number, h: number, d: number) => new THREE.Box3(new THREE.Vector3(0, 0, 0), new THREE.Vector3(w, h, d));
  it("frames every device at 45 to 55 percent of the short side, small ones smaller", () => {
    const keyboard = sceneFill(dev(355, 130, 38));
    const mouse = sceneFill(dev(62, 105, 38));
    const handheld = sceneFill(dev(91, 151, 36));
    expect(keyboard).toBeCloseTo(0.55, 2);
    expect(mouse).toBeGreaterThanOrEqual(0.45);
    expect(mouse).toBeLessThan(handheld);
    expect(handheld).toBeLessThan(keyboard);
    expect(sceneFill(dev(2000, 2000, 2000))).toBeLessThanOrEqual(0.55);
    expect(sceneFill(dev(1, 1, 1))).toBeGreaterThanOrEqual(0.45);
  });
});
