// SPEC 3.2 and 3.3: build space math, without three.js so it is easy to test.
import type { Layout, LayoutKey, Placement } from "../spec/types";

export type V3 = [number, number, number];

const DEG = Math.PI / 180;

export function rotateZ(v: V3, deg: number): V3 {
  const a = deg * DEG;
  const c = Math.cos(a);
  const s = Math.sin(a);
  return [v[0] * c - v[1] * s, v[0] * s + v[1] * c, v[2]];
}

/** Intrinsic Euler XYZ (three.js order "XYZ"): R = Rx * Ry * Rz applied to v. */
export function rotateXYZ(v: V3, deg: number[]): V3 {
  const [ax, ay, az] = [(deg[0] ?? 0) * DEG, (deg[1] ?? 0) * DEG, (deg[2] ?? 0) * DEG];
  // Rz
  let [x, y, z] = v;
  [x, y] = [x * Math.cos(az) - y * Math.sin(az), x * Math.sin(az) + y * Math.cos(az)];
  // Ry
  [x, z] = [x * Math.cos(ay) + z * Math.sin(ay), -x * Math.sin(ay) + z * Math.cos(ay)];
  // Rx
  [y, z] = [y * Math.cos(ax) - z * Math.sin(ax), y * Math.sin(ax) + z * Math.cos(ax)];
  return [x, y, z];
}

export interface ElementPose {
  index: number;
  /** World position in mm (before explode). */
  position: V3;
  /** Placement rotation in degrees (XYZ). */
  rotation: V3;
  /** Extra yaw about the element's own Z, degrees (= -r_deg). */
  yaw: number;
  /** Key size in units, for keycap footprints. */
  w_u: number;
  h_u: number;
}

/** Centre of one key in the instance frame (before placement). */
export function keyCentreLocal(k: LayoutKey, px: number, py: number): V3 {
  const w = k.w_u ?? 1;
  const h = k.h_u ?? 1;
  const r = k.r_deg ?? 0;
  const rx = k.rx_u ?? 0;
  const ry = k.ry_u ?? 0;
  const local: V3 = [(k.x_u + w / 2) * px, -(k.y_u + h / 2) * py, 0];
  const pivot: V3 = [rx * px, -ry * py, 0];
  const rel: V3 = [local[0] - pivot[0], local[1] - pivot[1], 0];
  const rot = rotateZ(rel, -r);
  return [rot[0] + pivot[0], rot[1] + pivot[1], 0];
}

function v3(a: number[] | undefined): V3 {
  return [a?.[0] ?? 0, a?.[1] ?? 0, a?.[2] ?? 0];
}

/** Every element of an instance, in world space (SPEC 3.3). */
export function elementPoses(placement: Placement, quantity: number, layout: Layout | undefined): ElementPose[] {
  const pos = v3(placement.position_mm);
  const rot = v3(placement.rotation_deg);
  if (placement.mode !== "layout" || !layout) {
    return Array.from({ length: Math.max(1, quantity) }, (_, i) => ({
      index: i,
      position: pos,
      rotation: rot,
      yaw: 0,
      w_u: 1,
      h_u: 1,
    }));
  }
  const widths = placement.key_widths_u;
  const keys = [...layout.keys]
    .filter((k) => !widths || widths.some((w) => Math.abs(w - (k.w_u ?? 1)) < 1e-6))
    .sort((a, b) => a.i - b.i);
  return keys.map((k) => {
    const c = rotateXYZ(keyCentreLocal(k, layout.pitch_x_mm, layout.pitch_y_mm), rot);
    return {
      index: k.i,
      position: [pos[0] + c[0], pos[1] + c[1], pos[2] + c[2]],
      rotation: rot,
      yaw: -(k.r_deg ?? 0),
      w_u: k.w_u ?? 1,
      h_u: k.h_u ?? 1,
    };
  });
}

export function addScaled(a: V3, b: number[] | undefined, f: number): V3 {
  const o = v3(b);
  return [a[0] + o[0] * f, a[1] + o[1] * f, a[2] + o[2] * f];
}

/** Extents of a layout in the instance frame, in mm (for PCB and plate placeholders). */
export function layoutExtents(layout: Layout): { min: V3; max: V3 } {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const k of layout.keys) {
    const c = keyCentreLocal(k, layout.pitch_x_mm, layout.pitch_y_mm);
    const hw = ((k.w_u ?? 1) * layout.pitch_x_mm) / 2;
    const hh = ((k.h_u ?? 1) * layout.pitch_y_mm) / 2;
    const reach = Math.hypot(hw, hh);
    const r = k.r_deg ?? 0;
    const ex = r === 0 ? hw : reach;
    const ey = r === 0 ? hh : reach;
    minX = Math.min(minX, c[0] - ex);
    maxX = Math.max(maxX, c[0] + ex);
    minY = Math.min(minY, c[1] - ey);
    maxY = Math.max(maxY, c[1] + ey);
  }
  if (!Number.isFinite(minX)) return { min: [0, 0, 0], max: [0, 0, 0] };
  return { min: [minX, minY, 0], max: [maxX, maxY, 0] };
}
