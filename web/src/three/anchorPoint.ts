// Where a label's leader line lands: a point on the part's own visible surface, found by casting
// rays from the camera through a grid over the part's footprint on screen. Plain three.js, so it is
// unit tested without a canvas.
import * as THREE from "three";

const GRID = 5;
/** Share of the way from the middle to the outermost candidate that the dot sits at (0 = centre, 1 = rim). */
const OUTWARD = 0.55;

/** Every drawn mesh under the owners (outline hulls opt out of raycasting by themselves). */
function meshesOf(owners: THREE.Object3D[]): THREE.Mesh[] {
  const out: THREE.Mesh[] = [];
  for (const o of owners)
    o.traverse((m) => {
      if ((m as THREE.Mesh).isMesh && m.visible) out.push(m as THREE.Mesh);
    });
  return out;
}

export interface AnchorHit {
  /** The surface point in the local space of `owner`, so it follows the part as the explode moves it. */
  local: THREE.Vector3;
  owner: THREE.Object3D;
}

/**
 * Picks the leader's landing point for one part: a point on one of its meshes that the camera sees
 * (`visible` says nothing from another part stands in front), preferring the side facing the label
 * column (the part's side of `modelMid`, the model's middle in screen x). The previous point is kept while
 * it stays in view so the dot does not wander as the camera turns. Null when no part of it is in view.
 */
export function findAnchorPoint(
  owners: THREE.Object3D[],
  camera: THREE.Camera,
  visible: (p: THREE.Vector3, owner: THREE.Object3D) => boolean,
  modelMid: number,
  prev: AnchorHit | null,
  /** True when another part shows through behind the point (a see-through shell over the display): such a dot reads as pointing at that part. */
  overlapped: (p: THREE.Vector3, owner: THREE.Object3D) => boolean = () => false,
): AnchorHit | null {
  if (prev && owners.includes(prev.owner)) {
    const p = prev.owner.localToWorld(prev.local.clone());
    if (visible(p, prev.owner) && !overlapped(p, prev.owner)) return prev;
  }
  const meshes = meshesOf(owners);
  if (!meshes.length) return null;
  const box = new THREE.Box3();
  for (const o of owners) box.expandByObject(o);
  if (box.isEmpty()) return null;
  let x0 = Infinity;
  let x1 = -Infinity;
  let y0 = Infinity;
  let y1 = -Infinity;
  const v = new THREE.Vector3();
  for (let i = 0; i < 8; i++) {
    v.set(i & 1 ? box.max.x : box.min.x, i & 2 ? box.max.y : box.min.y, i & 4 ? box.max.z : box.min.z).project(camera);
    x0 = Math.min(x0, v.x);
    x1 = Math.max(x1, v.x);
    y0 = Math.min(y0, v.y);
    y1 = Math.max(y1, v.y);
  }
  x0 = Math.max(-1, x0);
  x1 = Math.min(1, x1);
  y0 = Math.max(-1, y0);
  y1 = Math.min(1, y1);
  if (x1 <= x0 || y1 <= y0) return null;
  const ray = new THREE.Raycaster();
  const found: { p: THREE.Vector3; owner: THREE.Object3D; sx: number }[] = [];
  const ndc = new THREE.Vector2();
  for (let i = 0; i < GRID; i++)
    for (let j = 0; j < GRID; j++) {
      ndc.set(x0 + ((i + 0.5) / GRID) * (x1 - x0), y0 + ((j + 0.5) / GRID) * (y1 - y0));
      ray.setFromCamera(ndc, camera);
      const hit = ray.intersectObjects(meshes, false)[0];
      if (!hit) continue;
      const owner = owners.find((o) => {
        for (let x: THREE.Object3D | null = hit.object; x; x = x.parent) if (x === o) return true;
        return false;
      });
      if (owner) found.push({ p: hit.point.clone(), owner, sx: ndc.x });
    }
  if (!found.length) return null;
  // best first: those nearest the target column position, ties by distance from the part's middle on screen
  const mid = (x0 + x1) / 2;
  const half = Math.max(1e-6, (x1 - x0) / 2);
  const want = mid + Math.sign(mid - modelMid) * OUTWARD * half;
  found.sort((a, b) => Math.abs(a.sx - want) - Math.abs(b.sx - want));
  let fallback: AnchorHit | null = null;
  for (const f of found) {
    if (!visible(f.p, f.owner)) continue;
    const hit = { owner: f.owner, local: f.owner.worldToLocal(f.p.clone()) };
    if (!overlapped(f.p, f.owner)) return hit;
    fallback ??= hit;
  }
  return fallback ?? (prev && owners.includes(prev.owner) && visible(prev.owner.localToWorld(prev.local.clone()), prev.owner) ? prev : null);
}

/**
 * The part under a ray in the exploded view, as its focus key. A see-through shell (the case) is
 * passed through to what stands behind it and only counts when nothing else is there, so a click
 * on a part seen through the glass picks the part, never the case or a part that is not in view.
 */
export function partKeyAlong(hits: THREE.Intersection[], keyOf: (o: THREE.Object3D) => { key: string; shell: boolean } | undefined): string | null {
  let shell: string | null = null;
  for (const hit of hits) {
    const mesh = hit.object as THREE.Mesh;
    if (!mesh.isMesh || !mesh.visible) continue;
    const found = keyOf(hit.object);
    if (!found) continue;
    const m = mesh.material as THREE.Material | THREE.Material[];
    if (found.shell && !Array.isArray(m) && m.transparent && m.opacity < 0.5) {
      shell ??= found.key;
      continue;
    }
    return found.key;
  }
  return shell;
}

