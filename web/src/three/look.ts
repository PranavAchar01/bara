// How a layer group looks in the pick view: ghosted (faded) when another part is picked, or
// tinted when the pointer is over it. Materials are swapped for cached clones on the meshes, so
// shared materials elsewhere are never touched; the originals come back when the look ends.
import * as THREE from "three";

export type Look = "none" | "ghost" | "hover";

/** How much of its own opacity a ghosted part keeps at full ghost. */
const GHOST_KEEP = 0.14;
const HOVER_COLOR = new THREE.Color("#3B82F6");

const ghosts = new WeakMap<THREE.Material, THREE.Material>();
const hovers = new WeakMap<THREE.Material, THREE.Material>();
const isClone = new WeakSet<THREE.Material>();

function ghostOf(orig: THREE.Material): THREE.Material {
  let g = ghosts.get(orig);
  if (!g) {
    g = orig.clone();
    g.transparent = true;
    g.depthWrite = false;
    isClone.add(g);
    ghosts.set(orig, g);
  }
  return g;
}

function hoverOf(orig: THREE.Material): THREE.Material | null {
  if (!(orig as THREE.MeshStandardMaterial).isMeshStandardMaterial) return null;
  let h = hovers.get(orig);
  if (!h) {
    const m = orig.clone() as THREE.MeshStandardMaterial;
    m.emissive = HOVER_COLOR.clone();
    m.emissiveIntensity = 0.45;
    isClone.add(m);
    hovers.set(orig, m);
    h = m;
  }
  return h;
}

type Holder = THREE.Object3D & { material?: THREE.Material | THREE.Material[] };

/** Puts `look` on every mesh and line under `root`; amount 0..1 is how far a ghost has faded. */
export function setLook(root: THREE.Object3D, look: Look, amount = 1): void {
  root.traverse((o) => {
    const h = o as Holder;
    const mat = h.material;
    if (!mat || Array.isArray(mat)) return;
    const orig = isClone.has(mat) ? (h.userData.lookOrig as THREE.Material | undefined) : mat;
    if (!orig) return;
    if (look === "none" || amount <= 0.002) {
      if (mat !== orig) h.material = orig;
      return;
    }
    h.userData.lookOrig = orig;
    if (look === "ghost") {
      const g = ghostOf(orig);
      g.opacity = orig.opacity * (1 - (1 - GHOST_KEEP) * amount);
      if (h.material !== g) h.material = g;
      return;
    }
    const t = hoverOf(orig);
    if (t && h.material !== t) h.material = t;
  });
}
