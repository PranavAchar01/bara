// Focus: one part pulled out of the build. It moves to the middle of the stage and grows; every
// other part shrinks onto a shelf on the camera's left, in build order. Poses are computed once
// per focus change from the camera at that moment, then blended in by stage.focusK.
import { useEffect } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import * as THREE from "three";
import { focusPart, useApp } from "../state/store";
import { reducedMotion } from "../bot/spring";
import { stage } from "./stage";

const tmpBox = new THREE.Box3();
const tmpMat = new THREE.Matrix4();

/**
 * World box of the meshes under a group, instance by instance. Box3.setFromObject trusts an
 * InstancedMesh's cached bounds, which can be stale (empty) after the mesh remounts.
 */
export function meshBox(root: THREE.Object3D): THREE.Box3 {
  const out = new THREE.Box3();
  root.traverseVisible((o) => {
    const mesh = o as THREE.Mesh;
    if (!mesh.isMesh || !mesh.geometry) return;
    const geom = mesh.geometry;
    if (!geom.boundingBox) geom.computeBoundingBox();
    if (!geom.boundingBox || geom.boundingBox.isEmpty()) return;
    const inst = o as THREE.InstancedMesh;
    if (inst.isInstancedMesh) {
      for (let i = 0; i < inst.count; i++) {
        inst.getMatrixAt(i, tmpMat);
        out.union(tmpBox.copy(geom.boundingBox).applyMatrix4(tmpMat.premultiply(inst.matrixWorld)));
      }
    } else out.union(tmpBox.copy(geom.boundingBox).applyMatrix4(mesh.matrixWorld));
  });
  return out;
}

/** Content box of a group as it sits with no focus applied (explode only, scale 1). */
function restBox(g: THREE.Group): THREE.Box3 {
  const pos = g.position.clone();
  const scale = g.scale.x;
  g.position.set(0, 0, restZ(g));
  g.scale.setScalar(1);
  g.updateMatrixWorld(true);
  const out = meshBox(g);
  g.position.copy(pos);
  g.scale.setScalar(scale);
  g.updateMatrixWorld(true);
  return out;
}

/** The group's explode offset, written by its layer hook every frame. */
function restZ(g: THREE.Group): number {
  return typeof g.userData.restZ === "number" ? g.userData.restZ : g.position.z;
}

/** How wide a box looks along a screen axis (sum of its sides projected onto that axis). */
function extent(b: THREE.Box3, axis: THREE.Vector3): number {
  const sz = b.getSize(new THREE.Vector3());
  return Math.abs(axis.x) * sz.x + Math.abs(axis.y) * sz.y + Math.abs(axis.z) * sz.z;
}

/** Scale that fits a box inside w × h of the view plane. */
function fit(b: THREE.Box3, right: THREE.Vector3, up: THREE.Vector3, w: number, h: number): number {
  return Math.min(w / Math.max(extent(b, right), 1e-3), h / Math.max(extent(b, up), 1e-3));
}

/** Focus poses for every registered group, or an empty map when nothing is focused. */
export function focusPoses(key: string, camera: THREE.Camera): Map<THREE.Group, { pos: THREE.Vector3; scale: number }> {
  const poses = new Map<THREE.Group, { pos: THREE.Vector3; scale: number }>();
  // Rest layout: where each group sits with the current explode and no focus.
  const sets = new Map<string, { groups: THREE.Group[]; box: THREE.Box3; base: Map<THREE.Group, THREE.Vector3> }>();
  const whole = new THREE.Box3();
  for (const [g, k] of stage.focusGroups) {
    if (!g.visible) continue;
    const b = restBox(g);
    if (b.isEmpty()) continue;
    const set = sets.get(k) ?? { groups: [] as THREE.Group[], box: new THREE.Box3(), base: new Map<THREE.Group, THREE.Vector3>() };
    set.groups.push(g);
    set.box.union(b);
    // the explode offset is the only translation a group has at rest
    set.base.set(g, new THREE.Vector3(0, 0, restZ(g)));
    sets.set(k, set);
    whole.union(b);
  }
  const focused = sets.get(key);
  if (!focused || whole.isEmpty()) return poses;
  // Lay out in what the camera sees: a plane through the build, facing the camera.
  const cam = camera as THREE.PerspectiveCamera;
  cam.updateMatrixWorld();
  const eye = new THREE.Vector3().setFromMatrixPosition(cam.matrixWorld);
  const fwd = new THREE.Vector3();
  cam.getWorldDirection(fwd);
  const right = new THREE.Vector3().setFromMatrixColumn(cam.matrixWorld, 0).normalize();
  const up = new THREE.Vector3().setFromMatrixColumn(cam.matrixWorld, 1).normalize();
  const dist = Math.max(1, whole.getCenter(new THREE.Vector3()).sub(eye).dot(fwd));
  const halfH = dist * Math.tan(THREE.MathUtils.degToRad((cam.fov ?? 32) / 2));
  const halfW = halfH * (cam.aspect || 1.5);
  const mid = eye.clone().addScaledVector(fwd, dist);

  // The focused part: a little right of the middle of the view, filling about 60% of it.
  const fc = focused.box.getCenter(new THREE.Vector3());
  const s = THREE.MathUtils.clamp(fit(focused.box, right, up, 1.25 * halfW, 1.3 * halfH), 0.3, 8);
  const target = mid.clone().addScaledVector(right, 0.12 * halfW);
  for (const g of focused.groups) {
    const base = focused.base.get(g)!;
    poses.set(g, { pos: target.clone().add(base.clone().sub(fc).multiplyScalar(s)), scale: s });
  }

  // The rest: a shelf down the left fifth of the view, top to bottom in the order the build stacks them.
  const rest = [...sets.entries()].filter(([k]) => k !== key).sort((a, b) => b[1].box.max.z - a[1].box.max.z);
  const n = rest.length;
  const span = 1.5 * halfH;
  const step = n > 1 ? span / (n - 1) : 0;
  const slot = Math.min(n > 1 ? step : span, 0.45 * halfH, 0.3 * halfW);
  const top = mid.clone().addScaledVector(right, -0.72 * halfW).addScaledVector(up, span / 2);
  rest.forEach(([, set], i) => {
    const c = set.box.getCenter(new THREE.Vector3());
    const sc = THREE.MathUtils.clamp(fit(set.box, right, up, 0.42 * halfW, 0.9 * slot), 0.02, 0.6);
    const at = top.clone().addScaledVector(up, -i * step);
    for (const g of set.groups) {
      const base = set.base.get(g)!;
      poses.set(g, { pos: at.clone().add(base.clone().sub(c).multiplyScalar(sc)), scale: sc });
    }
  });
  return poses;
}

let focusCamera: THREE.Camera | null = null;

/**
 * True when a click at (x, y) in canvas pixels lands on or near the focused part (within 12% of
 * the view of its outline): a click in a gap between keys shouldn't put the part back.
 */
export function nearFocused(x: number, y: number, width: number, height: number): boolean {
  const key = useApp.getState().focusKey;
  if (!key || !focusCamera) return false;
  const box = new THREE.Box3();
  for (const [g, k] of stage.focusGroups) if (k === key) box.union(meshBox(g));
  if (box.isEmpty()) return false;
  let x0 = Infinity;
  let y0 = Infinity;
  let x1 = -Infinity;
  let y1 = -Infinity;
  const p = new THREE.Vector3();
  for (let i = 0; i < 8; i++) {
    p.set(i & 1 ? box.max.x : box.min.x, i & 2 ? box.max.y : box.min.y, i & 4 ? box.max.z : box.min.z).project(focusCamera);
    const sx = ((p.x + 1) / 2) * width;
    const sy = ((1 - p.y) / 2) * height;
    x0 = Math.min(x0, sx);
    y0 = Math.min(y0, sy);
    x1 = Math.max(x1, sx);
    y1 = Math.max(y1, sy);
  }
  const pad = 0.12 * Math.min(width, height);
  return x >= x0 - pad && x <= x1 + pad && y >= y0 - pad && y <= y1 + pad;
}

/** Inside the Canvas: recomputes poses when focus changes and eases focusK toward it. */
export function FocusDriver() {
  const key = useApp((s) => s.focusKey);
  const explode = useApp((s) => s.explode);
  const revision = useApp((s) => `${s.build?.revision ?? 0}:${s.build?.parts.length ?? 0}`);
  const { camera, invalidate } = useThree();
  focusCamera = camera;
  // Focus while exploded is a pick: the part stays in its layer (lifted a little), the rest ghost.
  const picking = key !== null && explode > 0.5;
  useEffect(() => {
    if (key && picking) {
      stage.focusPose = new Map();
      stage.pickKey = key;
    } else if (key) {
      stage.pickKey = null;
      stage.focusPose = focusPoses(key, camera);
      // nothing to pull out (its group isn't drawn): drop the focus rather than move everything
      if (stage.focusPose.size === 0) focusPart(null);
    }
    invalidate();
    // the shelf is laid out again when the explode slider moves under the focus
  }, [key, picking, explode, revision, camera, invalidate]);
  useFrame((_, dt) => {
    const pt = picking ? 1 : 0;
    const pd = pt - stage.pickK;
    if (Math.abs(pd) < 0.002) {
      if (stage.pickK !== pt) stage.pickK = pt;
      if (pt === 0 && stage.pickKey && !key) stage.pickKey = null;
    } else {
      stage.pickK = reducedMotion() ? pt : stage.pickK + pd * (1 - Math.exp(-dt * (pt ? 9 : 12)));
      invalidate();
    }
    const target = key && !picking && stage.focusPose.size ? 1 : 0;
    const d = target - stage.focusK;
    if (Math.abs(d) < 0.001) {
      if (stage.focusK !== target) stage.focusK = target;
      if (target === 0 && stage.focusPose.size) stage.focusPose.clear();
      return;
    }
    // ~420 ms in, ~320 ms out; reduced motion jumps
    stage.focusK = reducedMotion() ? target : stage.focusK + d * (1 - Math.exp(-dt * (target ? 9 : 12)));
    invalidate();
  });
  return null;
}
