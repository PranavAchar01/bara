// Footprint geometry for boards: courtyard corners and one hover box per
// footprint, from the board GLB's refdes nodes when loaded, else from the
// board record. Plain three.js, no React, so it is unit tested.
import * as THREE from "three";
import type { Board, BoardFootprint } from "../spec/types";
import type { LoadedModel } from "./assets";

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

/** One box per footprint: from the GLB when it is loaded, else from the record's courtyards. */
export function footprintBoxes(board: Board, model: Pick<LoadedModel, "footprints"> | null): HoverBox[] {
  const byRef = new Map((board.footprints ?? []).map((f) => [f.ref, f]));
  if (model?.footprints.length) {
    return model.footprints.map((f) => ({ ref: f.ref, box: f.box, footprint: byRef.get(f.ref) ?? null }));
  }
  const top = board.thickness_mm ?? 1.6;
  const out: HoverBox[] = [];
  for (const fp of board.footprints ?? []) {
    const pts = courtyard(fp);
    if (!pts) continue;
    const box = new THREE.Box3();
    for (const p of pts) box.expandByPoint(new THREE.Vector3(p.x, p.y, top));
    box.max.z = top + FLAT_FOOTPRINT_MM;
    out.push({ ref: fp.ref, box, footprint: fp });
  }
  return out;
}

