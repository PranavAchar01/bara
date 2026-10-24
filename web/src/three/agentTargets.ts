// Where each 3D part sits on screen, for the agent on stage (bot/agent.ts).
// Parts register their root object (and, when they know it, a local box in
// that object's space); AgentTargetProbe, inside the Canvas, keeps the camera
// and canvas element. partRect projects the part's world box to client pixels
// on demand, with no allocation besides the returned rect.
import { useEffect } from "react";
import { useThree } from "@react-three/fiber";
import * as THREE from "three";
import type { Rect } from "../bot/agent";

interface Entry {
  obj: THREE.Object3D;
  /** Box in obj's local space; null measures the object's meshes (Box3.setFromObject). */
  local: THREE.Box3 | null;
}

const parts = new Map<string, Entry>();
let camera: THREE.Camera | null = null;
let canvasEl: HTMLCanvasElement | null = null;

/** Registers a part's root object under its instance_id; returns the unregister. */
export function registerPart(id: string, obj: THREE.Object3D, local: THREE.Box3 | null = null): () => void {
  const e: Entry = { obj, local };
  parts.set(id, e);
  return () => {
    if (parts.get(id) === e) parts.delete(id);
  };
}

/** Inside the Canvas: stores the camera and the canvas element for partRect. */
export function AgentTargetProbe() {
  const cam = useThree((s) => s.camera);
  const el = useThree((s) => s.gl.domElement);
  useEffect(() => {
    camera = cam;
    canvasEl = el;
    return () => {
      if (camera === cam) camera = null;
      if (canvasEl === el) canvasEl = null;
    };
  }, [cam, el]);
  return null;
}

// The canvas rect, re-read at most once per ~frame (getBoundingClientRect allocates).
let cr: DOMRect | null = null;
let crAt = -1;
function clientRect(): DOMRect | null {
  if (!canvasEl || !canvasEl.isConnected) return null;
  const now = performance.now();
  if (!cr || now - crAt > 8) {
    cr = canvasEl.getBoundingClientRect();
    crAt = now;
  }
  return cr;
}

/** Client-pixel rect of the 3D canvas, or null when not mounted. */
export function canvasRect(): Rect | null {
  const r = clientRect();
  return r ? { x: r.left, y: r.top, w: r.width, h: r.height } : null;
}

const box = new THREE.Box3();
const v = new THREE.Vector3();

/**
 * Client-pixel rect of a part's on-screen bounds, or null when it is not in the scene / off screen.
 * Cheap enough to call every animation frame for one part. Pass `out` to reuse a rect.
 */
export function partRect(instanceId: string, out?: Rect): Rect | null {
  const e = parts.get(instanceId);
  const cam = camera;
  const r = clientRect();
  if (!e || !cam || !r || !e.obj.parent) return null;
  if (e.local) box.copy(e.local).applyMatrix4(e.obj.matrixWorld);
  else box.setFromObject(e.obj);
  if (box.isEmpty()) return null;
  const near = (cam as THREE.PerspectiveCamera).isPerspectiveCamera ? (cam as THREE.PerspectiveCamera).near : -Infinity;
  let x0 = Infinity;
  let y0 = Infinity;
  let x1 = -Infinity;
  let y1 = -Infinity;
  let front = 0;
  for (let i = 0; i < 8; i++) {
    v.set(i & 1 ? box.max.x : box.min.x, i & 2 ? box.max.y : box.min.y, i & 4 ? box.max.z : box.min.z).applyMatrix4(cam.matrixWorldInverse);
    // Corners behind the camera are pulled onto the near plane, so a part the camera sits in still frames.
    if (v.z > -near) v.z = -near;
    else front++;
    v.applyMatrix4(cam.projectionMatrix);
    x0 = Math.min(x0, v.x);
    x1 = Math.max(x1, v.x);
    y0 = Math.min(y0, v.y);
    y1 = Math.max(y1, v.y);
  }
  if (!front || x1 < -1 || x0 > 1 || y1 < -1 || y0 > 1) return null;
  const l = r.left + ((Math.max(-1, x0) + 1) / 2) * r.width;
  const ri = r.left + ((Math.min(1, x1) + 1) / 2) * r.width;
  const t = r.top + ((1 - Math.min(1, y1)) / 2) * r.height;
  const b = r.top + ((1 - Math.max(-1, y0)) / 2) * r.height;
  const o = out ?? { x: 0, y: 0, w: 0, h: 0 };
  o.x = l;
  o.y = t;
  o.w = ri - l;
  o.h = b - t;
  return o;
}
