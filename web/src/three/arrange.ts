// Where devices stand on the floor and where the camera goes, from their sizes alone.
// One general rule over bounding boxes (mm, x right, y back, z up), never per device type:
// bigger footprints come first, smaller ones stand to their right with a gap that scales with the
// smaller device, a long row wraps toward the front; the camera rises toward top-down for flat,
// wide things and settles at a 3/4 view for tall or handheld ones, turned so the long axis runs
// across the screen. No three.js, so it is easy to test.
import type { V3 } from "./layout";

export interface Box {
  min: V3;
  max: V3;
}

export interface CameraPlan {
  /** Unit vector from the target toward the camera. */
  dir: V3;
  /** Angle above the floor, degrees (90 = straight down). */
  elevationDeg: number;
  /** Turn away from straight-on, degrees (0 = looking along the long axis's normal). */
  yawDeg: number;
  /** Which floor axis runs across the screen. */
  across: "x" | "y";
  /** Height over footprint size: small is flat (a keyboard), large is tall (a lamp). */
  flatness: number;
}

export interface ScenePlan {
  /** Translation to apply to each input box: floor-aligned (min z = 0) and placed in the row. */
  offsets: V3[];
  /** The input boxes after the offsets. */
  placed: Box[];
  camera: CameraPlan;
}

const DEG = Math.PI / 180;
/** Gap between neighbours as a fraction of the smaller device's short footprint side. */
const GAP_FRAC = 0.5;
const GAP_MIN_MM = 12;
const GAP_MAX_MM = 80;
/** A row wraps when it would run longer than this many widths of its widest device. */
const ROW_LIMIT = 1.8;
/** Flatness (height / footprint) below which a view goes almost straight down, and above which it is 3/4. */
const FLAT_BELOW = 0.12;
const TALL_ABOVE = 0.7;
const ELEV_FLAT = 74;
const ELEV_TALL = 36;
const YAW_TALL = 29;

const sizeOf = (b: Box): V3 => [b.max[0] - b.min[0], b.max[1] - b.min[1], b.max[2] - b.min[2]];
const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
const smooth = (t: number) => t * t * (3 - 2 * t);

export function unionBox(boxes: Box[]): Box {
  const min: V3 = [Infinity, Infinity, Infinity];
  const max: V3 = [-Infinity, -Infinity, -Infinity];
  for (const b of boxes)
    for (let i = 0; i < 3; i++) {
      min[i] = Math.min(min[i], b.min[i]);
      max[i] = Math.max(max[i], b.max[i]);
    }
  return { min, max };
}

const shift = (b: Box, d: V3): Box => ({
  min: [b.min[0] + d[0], b.min[1] + d[1], b.min[2] + d[2]],
  max: [b.max[0] + d[0], b.max[1] + d[1], b.max[2] + d[2]],
});

/** Gap between two neighbouring devices: proportional to the smaller one's short side. */
export function gapBetween(a: Box, b: Box): number {
  const short = (x: Box) => Math.min(sizeOf(x)[0], sizeOf(x)[1]);
  return clamp(GAP_FRAC * Math.min(short(a), short(b)), GAP_MIN_MM, GAP_MAX_MM);
}

/**
 * Floor positions for the devices, in the order given back as one offset per input box.
 * Largest footprint first on the left; centred front to back within a row.
 */
export function arrangeDevices(boxes: Box[]): V3[] {
  const order = boxes
    .map((b, i) => ({ b, i, area: sizeOf(b)[0] * sizeOf(b)[1] }))
    .sort((p, q) => q.area - p.area || p.i - q.i);
  const widest = Math.max(1, ...order.map((o) => sizeOf(o.b)[0]));
  const rows: (typeof order)[] = [];
  let row: typeof order = [];
  let rowW = 0;
  for (const o of order) {
    const gap = row.length ? gapBetween(row[row.length - 1].b, o.b) : 0;
    if (row.length && rowW + gap + sizeOf(o.b)[0] > ROW_LIMIT * widest) {
      rows.push(row);
      row = [];
      rowW = 0;
    }
    rowW += (row.length ? gap : 0) + sizeOf(o.b)[0];
    row.push(o);
  }
  if (row.length) rows.push(row);

  const offsets: V3[] = boxes.map(() => [0, 0, 0]);
  let frontY = 0; // y of the back edge of the next row; rows step toward the front (-y)
  rows.forEach((r, ri) => {
    const depth = Math.max(...r.map((o) => sizeOf(o.b)[1]));
    const rowGap = ri === 0 ? 0 : Math.min(...r.map((o) => gapBetween(o.b, o.b)));
    frontY -= rowGap;
    const cy = frontY - depth / 2;
    let x = 0;
    r.forEach((o, k) => {
      if (k > 0) x += gapBetween(r[k - 1].b, o.b);
      const c: V3 = [(o.b.min[0] + o.b.max[0]) / 2, (o.b.min[1] + o.b.max[1]) / 2, 0];
      offsets[o.i] = [x - o.b.min[0], cy - c[1], -o.b.min[2]];
      x += sizeOf(o.b)[0];
    });
    frontY -= depth;
  });
  // centre the whole arrangement on x = 0 so nothing depends on the order of the inputs
  const placed = boxes.map((b, i) => shift(b, offsets[i]));
  const u = unionBox(placed);
  const cx = (u.min[0] + u.max[0]) / 2;
  const cy = (u.min[1] + u.max[1]) / 2;
  return offsets.map((o): V3 => [o[0] - cx, o[1] - cy, o[2]]);
}

/**
 * The camera for a set of placed boxes. Flat and wide goes high, near top-down; tall or small and
 * deep settles at a 3/4 view. The long footprint axis runs across the screen.
 */
export function chooseCamera(placed: Box[]): CameraPlan {
  const u = unionBox(placed);
  const [w, d, h] = sizeOf(u);
  const flatness = h / Math.max(1, Math.sqrt(Math.max(w, 1) * Math.max(d, 1)));
  const t = smooth(clamp((flatness - FLAT_BELOW) / (TALL_ABOVE - FLAT_BELOW), 0, 1));
  const elevationDeg = ELEV_FLAT + (ELEV_TALL - ELEV_FLAT) * t;
  // a flat view looks straight along the short axis; a 3/4 view turns a little to show a side
  const yawDeg = YAW_TALL * t;
  const across: "x" | "y" = d > w * 1.15 ? "y" : "x";
  const e = elevationDeg * DEG;
  const base = across === "x" ? [0, -1] : [-1, 0];
  const th = -yawDeg * DEG;
  const hx = base[0] * Math.cos(th) - base[1] * Math.sin(th);
  const hy = base[0] * Math.sin(th) + base[1] * Math.cos(th);
  return { dir: [hx * Math.cos(e), hy * Math.cos(e), Math.sin(e)], elevationDeg, yawDeg, across, flatness };
}

/** Floor layout and camera for a set of device boxes. */
export function planScene(boxes: Box[]): ScenePlan {
  const offsets = arrangeDevices(boxes);
  const placed = boxes.map((b, i) => shift(b, offsets[i]));
  return { offsets, placed, camera: chooseCamera(placed) };
}
