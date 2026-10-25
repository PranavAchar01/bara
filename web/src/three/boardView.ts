// The home view of a KiCad board GLB (Y up, board in the XZ plane): the three-quarter angle KiCad's own
// render uses for the board's poster (25 degrees round, 50 degrees up), so the live view lands where the
// poster was. The distance is the nearest one at which every corner of the board's box falls inside the
// wanted share of the frame.
import * as THREE from "three";

const AZIMUTH = THREE.MathUtils.degToRad(25);
const ELEVATION = THREE.MathUtils.degToRad(50);
export const HOME_DIR = new THREE.Vector3(Math.sin(AZIMUTH) * Math.cos(ELEVATION), Math.sin(ELEVATION), Math.cos(AZIMUTH) * Math.cos(ELEVATION));

/** Largest |x| / fillX or |y| / fillY of the box's corners in normalised device coordinates. */
function spread(cam: THREE.PerspectiveCamera, corners: THREE.Vector3[], fillX: number, fillY: number): number {
  let k = 0;
  const q = new THREE.Vector3();
  for (const p of corners) {
    q.copy(p).project(cam);
    k = Math.max(k, Math.abs(q.x) / fillX, Math.abs(q.y) / fillY);
  }
  return k;
}

export function homeView(box: THREE.Box3, fovDeg: number, aspect: number, fillX = 0.62, fillY = 0.65): { position: THREE.Vector3; target: THREE.Vector3; distance: number } {
  const target = box.getCenter(new THREE.Vector3());
  const radius = Math.max(box.getSize(new THREE.Vector3()).length() / 2, 1e-6);
  const corners: THREE.Vector3[] = [];
  for (const x of [box.min.x, box.max.x]) for (const y of [box.min.y, box.max.y]) for (const z of [box.min.z, box.max.z]) corners.push(new THREE.Vector3(x, y, z));
  const cam = new THREE.PerspectiveCamera(fovDeg, Math.max(0.2, aspect), radius / 1000, radius * 1000);
  const place = (d: number) => {
    cam.position.copy(target).addScaledVector(HOME_DIR, d);
    cam.lookAt(target);
    cam.updateMatrixWorld();
  };
  // fits at `hi`, too close at `lo`: halve the gap until the frame is filled to within a fraction of a percent
  let lo = radius * 1.01;
  let hi = radius * 200;
  for (let i = 0; i < 40; i++) {
    const mid = (lo + hi) / 2;
    place(mid);
    if (spread(cam, corners, fillX, fillY) > 1) lo = mid;
    else hi = mid;
  }
  return { position: target.clone().addScaledVector(HOME_DIR, hi), target, distance: hi };
}
