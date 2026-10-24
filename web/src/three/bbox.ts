// Placeholder boxes (SPEC 11.4 "Missing asset"): use bbox_mm when the catalog
// gives one, else the board size, a "Size" key spec, or a default by part kind.
import type { BBox, Board, BuildPart, Layout } from "../spec/types";
import { layoutExtents, type V3 } from "./layout";

export interface Box {
  min: V3;
  max: V3;
}

const centred = (x: number, y: number, z: number): Box => ({ min: [-x / 2, -y / 2, 0], max: [x / 2, y / 2, z] });

/** Defaults by part_id prefix (catalog convention `prefix:name`), then by kind. */
const BY_PREFIX: [RegExp, Box][] = [
  [/^sw:.*choc/, centred(15, 15, 8)],
  [/^sw:/, centred(14, 14, 11.4)],
  [/^cap:/, centred(18, 18, 7.5)],
  [/^mod:(pro_micro|nice_nano|elite)/, centred(18, 33, 4)],
  [/^mod:xiao/, centred(17.5, 21, 3.5)],
  [/^mod:/, centred(22, 22, 4)],
  [/^disp:.*128x32/, centred(38, 12, 3.5)],
  [/^disp:/, centred(35.4, 33.5, 4)],
  [/^sens:/, centred(13, 10.5, 2.5)],
  [/^bat:/, centred(30, 12, 3)],
  [/^conn:.*trrs/, centred(6, 12, 5)],
  [/^conn:/, centred(9, 7, 3.5)],
  [/^cable:/, centred(6, 40, 4)],
  [/^enc:|^rot:/, centred(13, 14, 20)],
];

const BY_KIND: Record<string, Box> = {
  module: centred(22, 22, 4),
  component: centred(10, 10, 5),
  mechanical: centred(20, 20, 3),
  fastener: centred(3, 3, 6),
  cable: centred(6, 40, 4),
  pcb: centred(60, 40, 1.6),
  other: centred(15, 15, 5),
};

/** Parse a key spec like "30 x 12 x 3" (mm). */
function sizeFromSpecs(part: BuildPart): Box | null {
  for (const k of part.card.key_specs ?? []) {
    if (!/size|dimension/i.test(k.label) || typeof k.value !== "string") continue;
    const nums = k.value.split(/[x×*]/i).map((s) => Number.parseFloat(s));
    if (nums.length === 3 && nums.every((n) => Number.isFinite(n) && n > 0)) return centred(nums[0], nums[1], nums[2]);
  }
  return null;
}

function thicknessFromSpecs(part: BuildPart): number | null {
  for (const k of part.card.key_specs ?? []) {
    if (/thick/i.test(k.label)) {
      const n = typeof k.value === "number" ? k.value : Number.parseFloat(String(k.value));
      if (Number.isFinite(n) && n > 0) return n;
    }
  }
  return null;
}

export interface BoxContext {
  layouts: Layout[];
  boards: Board[];
  parts: BuildPart[];
  catalogBbox?: BBox | null;
}

/**
 * Box for one element of a part, in the part's own frame. PCBs and plates
 * follow the switch layout on the same side (their origin is the layout
 * origin), falling back to the board size anchored at the origin.
 */
export function placeholderBox(part: BuildPart, ctx: BoxContext): Box {
  const kind = String(part.card.kind);
  if (ctx.catalogBbox?.min && ctx.catalogBbox?.max) {
    return { min: ctx.catalogBbox.min as V3, max: ctx.catalogBbox.max as V3 };
  }
  const isPlate = /plate/.test(part.part_id);
  if (kind === "pcb" || isPlate) {
    const t = kind === "pcb" ? (ctx.boards.find((b) => b.part_instance_id === part.instance_id)?.thickness_mm ?? 1.6) : (thicknessFromSpecs(part) ?? 1.5);
    const sibling = ctx.parts.find(
      (p) =>
        p.placement.mode === "layout" &&
        p.side === part.side &&
        p.placement.position_mm[0] === part.placement.position_mm[0] &&
        p.placement.position_mm[1] === part.placement.position_mm[1],
    );
    const layout = sibling ? ctx.layouts.find((l) => l.layout_id === sibling.placement.layout_id) : undefined;
    if (layout) {
      const e = layoutExtents(layout);
      const m = kind === "pcb" ? 2.5 : 1;
      return { min: [e.min[0] - m, e.min[1] - m, 0], max: [e.max[0] + m, e.max[1] + m, t] };
    }
    const board = ctx.boards.find((b) => b.part_instance_id === part.instance_id);
    const size = board?.size_mm;
    if (size && size.length >= 2) return { min: [0, -size[1], 0], max: [size[0], 0, t] };
  }
  const spec = sizeFromSpecs(part);
  if (spec) return spec;
  for (const [re, box] of BY_PREFIX) if (re.test(part.part_id)) return box;
  return BY_KIND[kind] ?? BY_KIND.other;
}
