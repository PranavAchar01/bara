import { afterEach, describe, expect, it } from "vitest";
import * as THREE from "three";
import { focusPoses } from "./focus";
import { stage } from "./stage";

function part(key: string, size: [number, number, number], z: number): THREE.Group {
  const g = new THREE.Group();
  g.add(new THREE.Mesh(new THREE.BoxGeometry(...size)));
  g.position.z = z;
  g.userData.restZ = z;
  stage.focusGroups.set(g, key);
  return g;
}

function camera(): THREE.PerspectiveCamera {
  const cam = new THREE.PerspectiveCamera(32, 1.6, 1, 5000);
  cam.up.set(0, 0, 1);
  cam.position.set(0, -600, 300);
  cam.lookAt(0, 0, 40);
  cam.updateMatrixWorld();
  return cam;
}

/** Where a pose puts the group's content centre on screen (x, y in -1..1). */
function onScreen(g: THREE.Group, pose: { pos: THREE.Vector3; scale: number }, cam: THREE.Camera): THREE.Vector3 {
  g.position.copy(pose.pos);
  g.scale.setScalar(pose.scale);
  g.updateMatrixWorld(true);
  return new THREE.Box3().setFromObject(g).getCenter(new THREE.Vector3()).project(cam);
}

describe("focus layout", () => {
  afterEach(() => stage.focusGroups.clear());

  it("pulls the focused part to the middle and grows a small one", () => {
    const mcu = part("p:mcu", [18, 33, 4], 60);
    const board = part("b:board", [300, 100, 2], 0);
    const cam = camera();
    const poses = focusPoses("p:mcu", cam);
    const p = poses.get(mcu)!;
    expect(p.scale).toBeGreaterThan(2);
    const c = onScreen(mcu, p, cam);
    expect(Math.abs(c.x)).toBeLessThan(0.3);
    expect(Math.abs(c.y)).toBeLessThan(0.3);
    // the board goes to the shelf on the left, shrunk
    const b = poses.get(board)!;
    expect(b.scale).toBeLessThan(0.6);
    expect(onScreen(board, b, cam).x).toBeLessThan(-0.4);
  });

  it("keeps the halves of a split part together", () => {
    const left = part("p:switches", [100, 80, 10], 30);
    const right = part("p:switches", [100, 80, 10], 30);
    right.children[0].position.x = 140;
    part("p:keycaps", [240, 80, 8], 60);
    const poses = focusPoses("p:switches", camera());
    expect(poses.get(left)!.scale).toBeCloseTo(poses.get(right)!.scale);
  });

  it("does nothing for a key with no drawn part", () => {
    part("p:mcu", [18, 33, 4], 60);
    expect(focusPoses("p:nothing", camera()).size).toBe(0);
  });
});
