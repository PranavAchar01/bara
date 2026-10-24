import { describe, expect, it } from "vitest";
import * as THREE from "three";
import { AGENT_BLEND, agentDistance, agentPose, easeOut, fitDistance } from "./agentCam";

const cube = (c: [number, number, number], h: number) =>
  new THREE.Box3(new THREE.Vector3(c[0] - h, c[1] - h, c[2] - h), new THREE.Vector3(c[0] + h, c[1] + h, c[2] + h));

describe("fitDistance", () => {
  it("fits the sphere in the tighter axis", () => {
    const wide = fitDistance(10, 32, 2);
    const tall = fitDistance(10, 32, 0.5);
    expect(tall).toBeGreaterThan(wide);
    expect(wide).toBeCloseTo((10 * 1.3) / Math.sin((16 * Math.PI) / 180), 6);
  });
});

describe("agentDistance", () => {
  it("dollies in modestly", () => {
    expect(agentDistance(400, 50)).toBeCloseTo(400 * 0.82, 6);
  });
  it("never goes closer than the part fits", () => {
    expect(agentDistance(400, 380)).toBe(380);
  });
  it("never backs away from the current framing", () => {
    expect(agentDistance(400, 900)).toBe(400);
  });
});

describe("agentPose", () => {
  const cam = new THREE.Vector3(0, -300, 400);
  const target = new THREE.Vector3(0, 0, 0);
  it("moves the target part of the way toward the part and keeps the view direction", () => {
    const p = agentPose(cam, target, cube([100, 0, 0], 5), 32, 1.5);
    expect(p.target.x).toBeCloseTo(100 * AGENT_BLEND, 6);
    const dir = p.pos.clone().sub(p.target).normalize();
    expect(dir.distanceTo(cam.clone().normalize())).toBeLessThan(1e-9);
    expect(p.pos.distanceTo(p.target)).toBeCloseTo(p.dist, 6);
    expect(p.dist).toBeLessThan(500);
  });
  it("keeps a big part whole in view", () => {
    const p = agentPose(cam, target, cube([0, 0, 0], 150), 32, 1.5);
    expect(p.dist).toBe(500);
  });
});

describe("easeOut", () => {
  it("clamps and eases", () => {
    expect(easeOut(-1)).toBe(0);
    expect(easeOut(2)).toBe(1);
    expect(easeOut(0.5)).toBeGreaterThan(0.5);
  });
});
