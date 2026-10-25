// Mutable per-frame state shared by the viewport's three.js components. Kept
// out of React state so the explode animation and the label projection run
// every frame without re-rendering the tree.
import * as THREE from "three";
import type { LayerId } from "./explode";

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
  /** Devices standing beside the build on the same canvas (Viewport3D CompanionRow); framed with it. */
  companions: null as THREE.Group | null,
  /** Displayed explode factor, eased toward the slider value. */
  explode: 0,
  /** True while the explode runs its staggered open or close (the slider moves every layer together). */
  stagger: false,
  /** Highest explode rank among the layers on stage, for the stagger. */
  rankTop: 7,
  /** Explode layer gap in mm for the current build. */
  gap: 20,
  /** True while the explode is still moving. */
  moving: false,
  /** Bumped when the explode settles after moving (shadow re-bake, framing). */
  settleVersion: 0,
  /** True while the camera eases to a new pose (on-demand rendering keeps drawing). */
  animating: false,
  anchors: new Map<string, LabelAnchor[]>(),
  /** Every part group by its focus key (label key), so focus can move them as sets. */
  focusGroups: new Map<THREE.Group, string>(),
  /** 0 = the build as laid out, 1 = one part pulled to the centre and the rest on the shelf. */
  focusK: 0,
  /** Where each group sits at focusK = 1 (position, uniform scale). */
  focusPose: new Map<THREE.Group, { pos: THREE.Vector3; scale: number }>(),
  /** Pick view (focus while exploded): the part stays in its layer, lifts a little, the rest ghost. */
  pickKey: null as string | null,
  /** 0 = nothing picked, 1 = the pick fully in (eased). */
  pickK: 0,
  /** The part under the pointer in the exploded view (focus key), or null. */
  hoverKey: null as string | null,
  /** Every layer group by its layer, so their real heights can be measured. */
  layerGroups: new Map<THREE.Group, LayerId>(),
  /** Extra height tier of a part group within its layer (see tiersByX). */
  tier: new Map<THREE.Group, number>(),
  /** Height of one tier in mm at explode = 1. */
  tierStep: 0,
  /** Measured exploded offset per layer in mm at explode = 1, or null until measured. */
  layerZ: null as Partial<Record<LayerId, number>> | null,
  /** Height of the tallest exploded offset (mm at explode = 1), for framing. */
  lift: 0,
};

/** How far the focus or pick view has taken the scene away from the plain build, 0 to 1. */
export const focusAmount = (): number => Math.max(stage.focusK, stage.pickK);

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
  const side = companionBox();
  if (side) box.union(side);
  return box.isEmpty() ? null : box;
}

/** The devices beside the build, or null when there are none on screen. */
export function companionBox(): THREE.Box3 | null {
  const g = stage.companions;
  if (!g || !g.children.length) return null;
  g.updateMatrixWorld(true);
  const box = new THREE.Box3().setFromObject(g);
  return box.isEmpty() ? null : box;
}
