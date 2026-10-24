// Mutable per-frame state shared by the viewport's three.js components. Kept
// out of React state so the explode animation and the label projection run
// every frame without re-rendering the tree.
import * as THREE from "three";

export interface LabelAnchor {
  /** Label key: one label per catalog part (both halves share one label). */
  key: string;
  /** Current world-space anchor (follows the explode). */
  world: () => THREE.Vector3;
  /** The object the anchor sits on: a ray that hits it first means the anchor is in view. */
  owner?: () => THREE.Object3D | null;
}

export const stage = {
  /** Root group holding parts, boards and enclosures (framing and floor use it). */
  root: null as THREE.Group | null,
  /** Displayed explode factor, eased toward the slider value. */
  explode: 0,
  /** Explode layer gap in mm for the current build. */
  gap: 20,
  /** True while the explode is still moving. */
  moving: false,
  /** Bumped when the explode settles after moving (shadow re-bake, framing). */
  settleVersion: 0,
  /** True while the camera eases to a new pose (on-demand rendering keeps drawing). */
  animating: false,
  anchors: new Map<string, LabelAnchor[]>(),
};

export function registerAnchor(a: LabelAnchor): () => void {
  const list = stage.anchors.get(a.key) ?? [];
  list.push(a);
  stage.anchors.set(a.key, list);
  return () => {
    const l = stage.anchors.get(a.key);
    if (!l) return;
    const i = l.indexOf(a);
    if (i >= 0) l.splice(i, 1);
    if (!l.length) stage.anchors.delete(a.key);
  };
}

/** World box of everything under the stage root, or null when empty. */
export function stageBox(): THREE.Box3 | null {
  if (!stage.root) return null;
  stage.root.updateMatrixWorld(true);
  const box = new THREE.Box3().setFromObject(stage.root);
  return box.isEmpty() ? null : box;
}
