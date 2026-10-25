// Footprint geometry for boards: courtyard corners and one hover box per
// footprint, from the board GLB's refdes nodes when loaded, else from the
// board record. Plain three.js, no React, so it is unit tested.
import * as THREE from "three";
import type { Board, BoardFootprint } from "../spec/types";
import type { LoadedModel } from "./assets";
import type { LayerId } from "./explode";

const DEG = Math.PI / 180;
/** Height given to a courtyard box when the footprint has no model yet. */
const FLAT_FOOTPRINT_MM = 2;

/** Corners of a footprint courtyard in build space (z left to the caller). */
export function courtyard(fp: BoardFootprint): THREE.Vector2[] | null {
  if (!fp.center_mm || !fp.size_mm) return null;
  const [cx, cy] = fp.center_mm;
  const [w, h] = fp.size_mm;
  const r = (fp.rot_deg ?? 0) * DEG;
  const c = Math.cos(r);
  const s = Math.sin(r);
  return [
    [-w / 2, -h / 2],
    [w / 2, -h / 2],
    [w / 2, h / 2],
    [-w / 2, h / 2],
  ].map(([x, y]) => new THREE.Vector2(cx + x * c - y * s, cy + x * s + y * c));
}

export interface HoverBox {
  ref: string;
  box: THREE.Box3;
  footprint: BoardFootprint | null;
}

/**
 * One box per footprint: the GLB's when it is loaded, and the record's courtyard
 * for any footprint the GLB has no node for (no 3D model in the library).
 */
export function footprintBoxes(board: Board, model: Pick<LoadedModel, "footprints"> | null): HoverBox[] {
  const byRef = new Map((board.footprints ?? []).map((f) => [f.ref, f]));
  const out: HoverBox[] = (model?.footprints ?? []).map((f) => ({ ref: f.ref, box: f.box, footprint: byRef.get(f.ref) ?? null }));
  const have = new Set(out.map((h) => h.ref));
  const top = board.thickness_mm ?? 1.6;
  for (const fp of board.footprints ?? []) {
    if (have.has(fp.ref)) continue;
    const pts = courtyard(fp);
    if (!pts) continue;
    const box = new THREE.Box3();
    for (const p of pts) box.expandByPoint(new THREE.Vector3(p.x, p.y, top));
    box.max.z = top + FLAT_FOOTPRINT_MM;
    out.push({ ref: fp.ref, box, footprint: fp });
  }
  return out;
}

/** A part the board GLB may already show: its layer and element origins in build space. */
export interface BoardCandidate {
  instanceId: string;
  /** Catalog id; a footprint's library id appears in it for parts drawn from a KiCad footprint. */
  partId?: string;
  layer: LayerId;
  points: THREE.Vector3[];
}

export function boardMatrix(board: Board): THREE.Matrix4 {
  const pos = board.position_mm ?? [0, 0, 0];
  const rot = board.rotation_deg ?? [0, 0, 0];
  return new THREE.Matrix4().compose(
    new THREE.Vector3(pos[0], pos[1], pos[2]),
    new THREE.Quaternion().setFromEuler(new THREE.Euler(rot[0] * DEG, rot[1] * DEG, rot[2] * DEG, "XYZ")),
    new THREE.Vector3(1, 1, 1),
  );
}

/**
 * The routed board GLB is the assembly: kicad-cli exports every footprint's
 * model (switches, MCU, display, encoder) in place. Each small component
 * whose footprint holds a part's origin is that part; the part then draws no
 * mesh of its own, and the component lifts with the part's layer when the
 * view explodes. kicad-cli names each component by its footprint reference, so
 * a named one is matched through the board's footprint list whatever its size
 * (a handheld's display covers most of the board); the position test is the
 * fallback for unnamed components. The largest unclaimed component is the bare board.
 */
export function matchComponents(loaded: LoadedModel, board: Board, candidates: BoardCandidate[]) {
  const m = boardMatrix(board);
  const whole = loaded.bbox.clone().applyMatrix4(m);
  const boardArea = (whole.max.x - whole.min.x) * (whole.max.y - whole.min.y);
  const owner = new Map<number, BoardCandidate>();
  const byInstance = new Map(candidates.map((c) => [c.instanceId, c]));
  const byRef = new Map<string, BoardCandidate>();
  for (const fp of board.footprints ?? []) {
    const cand = fp.instance_id ? byInstance.get(fp.instance_id) : undefined;
    if (cand) byRef.set(fp.ref, cand);
  }
  // kicad-cli names every component by its footprint reference; a component that is one of the
  // board's footprints is a part's model, never the bare board, however much of the board it covers.
  const footprintByRef = new Map((board.footprints ?? []).map((f) => [f.ref, f]));
  let substrate = -1;
  let biggest = 0;
  loaded.components.forEach((c, i) => {
    if (c.bbox.isEmpty()) return;
    const named = byRef.get(c.name);
    if (named) {
      owner.set(i, named);
      return;
    }
    const b = c.bbox.clone().applyMatrix4(m);
    const area = (b.max.x - b.min.x) * (b.max.y - b.min.y);
    const listed = footprintByRef.has(c.name);
    if (!listed && area > biggest) {
      biggest = area;
      substrate = i;
    }
    if (!listed && area > boardArea * 0.25) return;
    const centre = b.getCenter(new THREE.Vector3());
    let best: BoardCandidate | null = null;
    let bestD = Infinity;
    for (const cand of candidates)
      for (const p of cand.points) {
        if (p.x < b.min.x - 0.5 || p.x > b.max.x + 0.5 || p.y < b.min.y - 0.5 || p.y > b.max.y + 0.5) continue;
        if (p.z < b.min.z - 2.5 || p.z > b.max.z + 2.5) continue;
        const d = Math.hypot(p.x - centre.x, p.y - centre.y);
        if (d < bestD) {
          bestD = d;
          best = cand;
        }
      }
    // A part placed once but fitted several times (a D-pad's four switches) has one point; its other
    // footprints share the part's library id.
    const lib = footprintByRef.get(c.name)?.lib_id;
    if (!best && lib) best = candidates.find((cand) => cand.partId?.includes(lib)) ?? null;
    if (best) owner.set(i, best);
  });
  return { owner, substrate };
}
