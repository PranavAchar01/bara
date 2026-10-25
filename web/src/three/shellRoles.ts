// Shell roles: which part of a case a mesh is (body, trim, buttons, accent buttons, screen glass),
// so each can wear its own palette colour. Roles come from the case's node names and from the
// shape of the button caps, never from the device. Buttons split into separate islands; the
// round set that repeats (two or more alike, not the biggest) are the action buttons.
import * as THREE from "three";

export type CaseRole = "body" | "trim" | "buttons" | "accent" | "screen";

export const CAPS_NAME = /(^|_)caps?$/i;
export const GLASS_NAME = /(^|_)glass$/i;

/** Connected pieces of one geometry (triangles sharing a vertex position), as separate geometries. */
export function islands(src: THREE.BufferGeometry): THREE.BufferGeometry[] {
  const g = src.index ? src.toNonIndexed() : src;
  const pos = g.attributes.position as THREE.BufferAttribute;
  const nor = g.attributes.normal as THREE.BufferAttribute | undefined;
  const tris = Math.floor(pos.count / 3);
  const parent = new Map<string, string>();
  const find = (k: string): string => {
    let r = k;
    while (parent.get(r) !== r) r = parent.get(r) as string;
    let c = k;
    while (parent.get(c) !== r) {
      const n = parent.get(c) as string;
      parent.set(c, r);
      c = n;
    }
    return r;
  };
  const key = (i: number) => `${Math.round(pos.getX(i) * 20)},${Math.round(pos.getY(i) * 20)},${Math.round(pos.getZ(i) * 20)}`;
  const keys: string[] = [];
  for (let i = 0; i < pos.count; i++) {
    const k = key(i);
    keys.push(k);
    if (!parent.has(k)) parent.set(k, k);
  }
  for (let t = 0; t < tris; t++) {
    const a = find(keys[t * 3]);
    parent.set(find(keys[t * 3 + 1]), a);
    parent.set(find(keys[t * 3 + 2]), a);
  }
  const byRoot = new Map<string, number[]>();
  for (let t = 0; t < tris; t++) {
    const r = find(keys[t * 3]);
    const l = byRoot.get(r) ?? [];
    l.push(t);
    byRoot.set(r, l);
  }
  return [...byRoot.values()].map((list) => {
    const p = new Float32Array(list.length * 9);
    const n = nor ? new Float32Array(list.length * 9) : null;
    list.forEach((t, j) => {
      for (let v = 0; v < 3; v++) {
        for (let c = 0; c < 3; c++) {
          p[j * 9 + v * 3 + c] = [pos.getX, pos.getY, pos.getZ][c].call(pos, t * 3 + v);
          if (n && nor) n[j * 9 + v * 3 + c] = [nor.getX, nor.getY, nor.getZ][c].call(nor, t * 3 + v);
        }
      }
    });
    const out = new THREE.BufferGeometry();
    out.setAttribute("position", new THREE.BufferAttribute(p, 3));
    if (n) out.setAttribute("normal", new THREE.BufferAttribute(n, 3));
    else out.computeVertexNormals();
    return out;
  });
}

/** Split button-cap geometries into plain buttons and action buttons (the round, repeated, not-largest set). */
export function splitButtons(caps: THREE.BufferGeometry[]): { buttons: THREE.BufferGeometry[]; accent: THREE.BufferGeometry[]; bars: THREE.BufferGeometry[] } {
  const all = caps.flatMap(islands).filter((g) => g.attributes.position.count >= 9);
  const info = all.map((g) => {
    g.computeBoundingBox();
    const s = new THREE.Vector3();
    (g.boundingBox as THREE.Box3).getSize(s);
    return { g, w: Math.max(s.x, s.y), h: Math.min(s.x, s.y) };
  });
  // long thin islands (shoulder triggers) are bars: they take the shell's trim, not a button colour
  const bars = info.filter((i) => i.h > 0 && i.w / i.h > 2.5);
  const barSet = new Set(bars.map((b) => b.g));
  const biggest = Math.max(0, ...info.map((i) => i.w));
  const round = info.filter((i) => !barSet.has(i.g) && i.h > 0 && i.w / i.h < 1.2 && i.w < biggest * 0.8);
  // size classes among the round ones; the most repeated class (2 to 4 alike) is the action set
  const classes = new Map<number, typeof round>();
  for (const r of round) {
    const k = Math.round(r.w * 2);
    classes.set(k, [...(classes.get(k) ?? []), r]);
  }
  const best = [...classes.values()].filter((c) => c.length >= 2 && c.length <= 4).sort((a, b) => b.length - a.length)[0] ?? [];
  const set = new Set(best.map((b) => b.g));
  return { buttons: all.filter((g) => !set.has(g) && !barSet.has(g)), accent: all.filter((g) => set.has(g)), bars: bars.map((b) => b.g) };
}
