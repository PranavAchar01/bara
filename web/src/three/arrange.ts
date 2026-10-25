// Where devices stand on the floor and where the camera goes, from their bounding boxes (mm,
// x right, y back, z up) and, when known, what kind of device each is.
// Kinds set the desk order (keyboard on the left, mouse on the right, a hand's width apart) and
// the view: a handheld from the front at a 3/4, flat things (keyboards, macropads, mice, boards)
// from high up, several devices from one high front view with the row across the screen.
// Without kinds one general rule over the boxes decides: bigger footprints first, smaller ones
// to their right with a gap that scales with the smaller device, a long row wraps toward the
// front; the camera rises toward top-down for flat, wide things and settles at a 3/4 view for
// tall ones, turned so the long axis runs across the screen. No three.js, so it is easy to test.
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
 * What sort of device a build is, read from its spec (taxonomy, class) and prompt. It only tunes
 * the layout and the camera; anything unrecognised is "other" and falls back to the size rule.
 */
export type DeviceKind = "keyboard" | "macropad" | "mouse" | "handheld" | "board" | "other";

export function deviceKind(info: { taxonomy?: readonly string[] | null; deviceClass?: string | null; prompt?: string | null }): DeviceKind {
  const spec = `${(info.taxonomy ?? []).join(" ")} ${info.deviceClass ?? ""}`.toLowerCase();
  const all = `${spec} ${info.prompt ?? ""}`.toLowerCase();
  const kind = (t: string): DeviceKind | null => {
    if (/macro ?pad|stream ?deck|\bkeypad|numpad|button ?box/.test(t)) return "macropad";
    if (/keyboard/.test(t)) return "keyboard";
    if (/\bmouse\b|\bmice\b/.test(t)) return "mouse";
    if (/handheld|game ?boy|console|gamepad|game controller|controller|remote|calculator|pager|tamagotchi|walkie|phone|mp3|music player/.test(t)) return "handheld";
    if (/dev ?board|breakout|\bboard\b|display|monitor|panel|hub|deck/.test(t)) return "board";
    return null;
  };
  // the spec's own taxonomy wins over words in the prompt ("a keyboard with a trackball" stays a keyboard)
  return kind(spec) ?? kind(all) ?? "other";
}

/** Kinds that lie flat on the desk and are used from above. */
const FLAT_KINDS: ReadonlySet<DeviceKind> = new Set(["keyboard", "macropad", "mouse", "board"]);

/** Left-to-right desk order: the keyboard first, the mouse last (on the right hand side). */
const DESK_RANK: Record<DeviceKind, number> = { keyboard: 0, macropad: 1, board: 2, other: 2, handheld: 3, mouse: 4 };

/** A mouse stands a hand's width from the keyboard, as on a desk. */
const MOUSE_GAP_MM = 55;

function deskGap(a: { b: Box; kind: DeviceKind }, b: { b: Box; kind: DeviceKind }): number {
  const g = gapBetween(a.b, b.b);
  return a.kind === "mouse" || b.kind === "mouse" ? Math.max(g, MOUSE_GAP_MM) : g;
}

/**
 * Floor positions for the devices, in the order given back as one offset per input box.
 * With kinds, the desk order comes first (keyboard left, mouse right); otherwise, and between
 * devices of one rank, the largest footprint goes first on the left. Centred front to back
 * within a row.
 */
export function arrangeDevices(boxes: Box[], kinds?: readonly (DeviceKind | null | undefined)[]): V3[] {
  const order = boxes
    .map((b, i) => ({ b, i, area: sizeOf(b)[0] * sizeOf(b)[1], kind: kinds?.[i] ?? "other" }))
    .sort((p, q) => DESK_RANK[p.kind] - DESK_RANK[q.kind] || q.area - p.area || p.i - q.i);
  const widest = Math.max(1, ...order.map((o) => sizeOf(o.b)[0]));
  const rows: (typeof order)[] = [];
  let row: typeof order = [];
  let rowW = 0;
  for (const o of order) {
    const gap = row.length ? deskGap(row[row.length - 1], o) : 0;
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
      if (k > 0) x += deskGap(r[k - 1], o);
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
  return { ...cameraAt(elevationDeg, yawDeg, across), flatness };
}

function cameraAt(elevationDeg: number, yawDeg: number, across: "x" | "y"): Omit<CameraPlan, "flatness"> {
  const e = elevationDeg * DEG;
  const base = across === "x" ? [0, -1] : [-1, 0];
  const th = -yawDeg * DEG;
  const hx = base[0] * Math.cos(th) - base[1] * Math.sin(th);
  const hy = base[0] * Math.sin(th) + base[1] * Math.cos(th);
  return { dir: [hx * Math.cos(e), hy * Math.cos(e), Math.sin(e)], elevationDeg, yawDeg, across };
}

/** One device on its own, by kind: elevation above the desk and turn, degrees. */
const SOLO_VIEW: Partial<Record<DeviceKind, [number, number]>> = {
  // flat things used from above: high, nearly straight on, so the whole top face reads
  board: [72, 6],
  keyboard: [64, 8],
  macropad: [62, 12],
  mouse: [56, 16],
  // a handheld from the front at a 3/4, its face upright toward the viewer
  handheld: [50, 22],
};
/** Several devices on a desk: a high view from the front, the row running across the screen. */
const DESK_VIEW: [number, number] = [60, 6];
/** A desk that also holds a handheld or something unknown: lower, so the taller pieces read too. */
const MIXED_VIEW: [number, number] = [52, 10];

/**
 * The camera for devices of known kinds, already placed (arrangeDevices). One device: by its kind,
 * a front view for a handheld and a high or near top-down one for flat things. Several: one high
 * front view over the whole row, the row across the screen. Without any known kind, the size rule
 * (chooseCamera) decides.
 */
export function layoutCamera(placed: Box[], kinds: readonly (DeviceKind | null | undefined)[]): CameraPlan {
  const size = chooseCamera(placed);
  const known = kinds.map((k) => k ?? "other");
  if (!placed.length || known.every((k) => k === "other")) return size;
  if (placed.length === 1) {
    const v = SOLO_VIEW[known[0]];
    return v ? { ...cameraAt(v[0], v[1], "x"), flatness: size.flatness } : size;
  }
  const v = known.every((k) => FLAT_KINDS.has(k)) ? DESK_VIEW : MIXED_VIEW;
  const u = unionBox(placed);
  // a row is wide; only a stack that wrapped deeper than wide turns to run across the screen
  const across: "x" | "y" = u.max[1] - u.min[1] > (u.max[0] - u.min[0]) * 1.4 ? "y" : "x";
  return { ...cameraAt(v[0], v[1], across), flatness: size.flatness };
}

export interface DeviceOnDesk {
  box: Box;
  kind?: DeviceKind | null;
}

/** Floor layout and camera for a set of devices, by their boxes and (when known) their kinds. */
export function planLayout(devices: DeviceOnDesk[]): ScenePlan {
  const boxes = devices.map((d) => d.box);
  const kinds = devices.map((d) => d.kind);
  const offsets = arrangeDevices(boxes, kinds);
  const placed = boxes.map((b, i) => shift(b, offsets[i]));
  return { offsets, placed, camera: layoutCamera(placed, kinds) };
}

/** Floor layout and camera for a set of device boxes, by size alone. */
export function planScene(boxes: Box[]): ScenePlan {
  return planLayout(boxes.map((box) => ({ box })));
}
