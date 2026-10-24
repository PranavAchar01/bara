import { describe, expect, it } from "vitest";
import * as THREE from "three";
import { caseOverhang } from "./Viewport3D";

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
