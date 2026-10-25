import { describe, expect, it } from "vitest";
import * as THREE from "three";
import { HOME_DIR, homeView } from "./boardView";

describe("board home view", () => {
  const board = new THREE.Box3(new THREE.Vector3(-0.05, 0, -0.03), new THREE.Vector3(0.05, 0.012, 0.03));

  it("looks down at the board from the poster's three-quarter angle", () => {
    const v = homeView(board, 32, 16 / 11);
    const dir = v.position.clone().sub(v.target).normalize();
    expect(dir.distanceTo(HOME_DIR)).toBeLessThan(1e-6);
    expect(dir.y).toBeGreaterThan(0.7);
  });

  it("fills the wanted share of the frame, no more", () => {
    const v = homeView(board, 32, 16 / 11);
    const cam = new THREE.PerspectiveCamera(32, 16 / 11, 0.001, 10);
    cam.position.copy(v.position);
    cam.lookAt(v.target);
    cam.updateMatrixWorld();
    let x = 0;
    let y = 0;
    for (const px of [board.min.x, board.max.x]) for (const py of [board.min.y, board.max.y]) for (const pz of [board.min.z, board.max.z]) {
      const q = new THREE.Vector3(px, py, pz).project(cam);
      x = Math.max(x, Math.abs(q.x));
      y = Math.max(y, Math.abs(q.y));
    }
    expect(Math.max(x / 0.62, y / 0.65)).toBeCloseTo(1, 2);
  });

  it("backs off for a bigger board", () => {
    const big = board.clone().expandByScalar(0.05);
    expect(homeView(big, 32, 1.4).distance).toBeGreaterThan(homeView(board, 32, 1.4).distance);
  });
});
