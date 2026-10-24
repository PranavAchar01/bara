// Camera drift toward the part the agent on stage is working on: pure pose maths
// (Viewport3D's AgentCam runs the timing and the guards).
import * as THREE from "three";

/** Share of the way the orbit target moves toward the part's centre. */
export const AGENT_BLEND = 0.4;
/** Share of the current distance the camera dollies in. */
export const AGENT_DOLLY = 0.18;
/** Margin over the part's bounding sphere that must stay in view. */
export const AGENT_MARGIN = 1.3;

/** Distance at which a sphere of `radius` fits the tighter half-angle of the view, with `margin`. */
export function fitDistance(radius: number, fovDeg: number, aspect: number, margin = AGENT_MARGIN): number {
  const tanV = Math.tan((fovDeg * Math.PI) / 360);
  const half = Math.min(Math.atan(tanV), Math.atan(tanV * Math.max(1e-3, aspect)));
  return (radius * margin) / Math.sin(half);
}

/**
 * New orbit distance: a modest dolly in from `current`, never closer than the
 * part fits, and never farther than `current` (the framing that already shows it).
 */
export function agentDistance(current: number, fit: number, dolly = AGENT_DOLLY): number {
  return Math.min(current, Math.max(fit, current * (1 - dolly)));
}

/**
 * Pose that keeps the current viewing direction, with the target eased `blend`
 * of the way toward the part's centre and the distance from agentDistance.
 */
export function agentPose(
  camPos: THREE.Vector3,
  target: THREE.Vector3,
  part: THREE.Box3,
  fovDeg: number,
  aspect: number,
  blend = AGENT_BLEND,
): { pos: THREE.Vector3; target: THREE.Vector3; dist: number } {
  const dir = camPos.clone().sub(target);
  const cur = dir.length();
  if (cur < 1e-6) dir.set(0, -1, 1);
  dir.normalize();
  const sphere = part.getBoundingSphere(new THREE.Sphere());
  const to = target.clone().lerp(sphere.center, blend);
  const dist = agentDistance(cur, fitDistance(sphere.radius, fovDeg, aspect));
  return { pos: to.clone().addScaledVector(dir, dist), target: to, dist };
}

/** Critically damped-looking ease for t in [0, 1] (cubic out). */
export function easeOut(t: number): number {
  const c = Math.min(1, Math.max(0, t));
  return 1 - Math.pow(1 - c, 3);
}
