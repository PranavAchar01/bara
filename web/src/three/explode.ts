// Exploded view: every part sits on one Z layer, stacked from the case floor up
// (case, battery, PCB, board parts, plate, switches, keycaps, top accessories).
// Pure functions so the order and the naming are unit tested.
import type { BuildPart } from "../spec/types";

export type LayerId = "case" | "under" | "pcb" | "board_parts" | "plate" | "switches" | "keycaps" | "top" | "lid";

export const LAYER_RANK: Record<LayerId, number> = {
  case: 0,
  under: 1,
  pcb: 2,
  board_parts: 3,
  plate: 4,
  switches: 5,
  keycaps: 6,
  top: 7,
  /** A closed case (lid over the board) lifts off above everything else. */
  lid: 8,
};
export const TOP_RANK = LAYER_RANK.top;

type PartLike = Pick<BuildPart, "part_id" | "card" | "label">;

function fn(p: PartLike): string {
  return `${p.card.primary_function ?? ""}`.toLowerCase();
}

function text(p: PartLike): string {
  return `${p.part_id} ${p.card.display_name} ${p.label ?? ""} ${fn(p)}`.toLowerCase();
}

export function isKeycapPart(p: PartLike): boolean {
  return p.part_id.startsWith("cap:") || /keycap/.test(fn(p));
}

export function layerOf(p: PartLike): LayerId {
  const id = p.part_id;
  const f = fn(p);
  const t = text(p);
  const kind = String(p.card.kind);
  if (isKeycapPart(p)) return "keycaps";
  // Key switches only: a slide power switch is a board part, not a keyboard layer.
  if (f === "input.key" || (id.startsWith("sw:") && !f)) return "switches";
  if (/plate/.test(id) || f === "mech.plate") return "plate";
  if (kind === "pcb" || f === "interconnect.pcb") return "pcb";
  if (id.startsWith("bat:") || /battery|power\.cell/.test(f)) return "under";
  if (/case|enclosure|foam|feet|bumper/.test(f) || /^case:|^foam:/.test(id)) return "case";
  if (/sensor/.test(f) && /trackball|pmw|optical/.test(t)) return "under";
  if (/trackball|\bball\b|knob|encoder|oled|screen/.test(t) || (/^display\./.test(f) && f !== "display.indicator_led") || /^disp:|^enc:|^rot:|^knob:|^ball:/.test(id)) return "top";
  return "board_parts";
}

/** Z gap between layers in mm, scaled to the footprint so the stack reads at any size. */
export function layerGap(footprintMm: number): number {
  return Math.min(48, Math.max(12, footprintMm * 0.2));
}

export function explodeZ(layer: LayerId, gapMm: number, factor: number): number {
  return LAYER_RANK[layer] * gapMm * factor;
}

/** Lowest and highest z (mm) a layer's content reaches as built. */
export type LayerExtent = [number, number];

/**
 * How far each layer lifts at full explode so the layers stand apart with `clearance` between the
 * top of one and the bottom of the next, whatever their real heights. Layers keep their build
 * order and never move down. Layers without an extent are left out. Parts that ride another
 * (keycaps on their switches) only ever move along z with it, so they stay over it.
 */
export function layerOffsets(ext: Partial<Record<LayerId, LayerExtent>>, clearance: number): Partial<Record<LayerId, number>> {
  const out: Partial<Record<LayerId, number>> = {};
  const order = (Object.keys(LAYER_RANK) as LayerId[]).filter((l) => ext[l]).sort((a, b) => LAYER_RANK[a] - LAYER_RANK[b]);
  let top = -Infinity; // highest point of everything below, in its lifted position
  let prev = 0;
  for (const l of order) {
    const [lo, hi] = ext[l]!;
    const off = top === -Infinity ? 0 : Math.max(prev, top + clearance - lo);
    out[l] = off;
    prev = off;
    top = Math.max(top, hi + off);
  }
  return out;
}

const GROUP_NAME: Record<LayerId, string> = {
  case: "Case",
  under: "",
  pcb: "PCB",
  board_parts: "",
  plate: "Plate",
  switches: "Switches",
  keycaps: "Keycaps",
  top: "",
  lid: "Case",
};

const BY_FUNCTION: [RegExp, string][] = [
  [/battery/, "Battery"],
  [/mcu|controller|compute/, "MCU"],
  [/indicator_led/, "LEDs"],
  [/oled|display|screen/, "Display"],
  [/trackball/, "Trackball"],
  [/encoder|knob/, "Knob"],
  [/jack|trrs/, "Jack"],
  [/usb|connector|interconnect\.(?!pcb|cable)/, "Connector"],
  [/cable/, "Cable"],
  [/sensor/, "Sensor"],
  [/diode/, "Diodes"],
  [/socket|hot.?swap/, "Hot-swap sockets"],
  [/led|rgb/, "LEDs"],
];

/** Short human name for a part ("Keycaps", "MCU"), never a raw catalog id.
 *  The plan's slot label ("Player/status LEDs") is the part's role, so it wins over
 *  guessing from keywords; whole layers (case, PCB, keycaps) keep their layer name. */
export function humanGroupName(p: PartLike): string {
  const layer = layerOf(p);
  if (GROUP_NAME[layer]) return GROUP_NAME[layer];
  const slot = p.label?.replace(/\s*\((left|right|l|r)\)\s*$/i, "").trim();
  if (slot) return slot;
  const t = `${fn(p)} ${p.card.display_name}`.toLowerCase();
  for (const [re, name] of BY_FUNCTION) if (re.test(t)) return name;
  return p.label ?? p.card.display_name;
}

export interface PartLabel {
  key: string;
  title: string;
  detail: string;
  sub: string;
  generated: boolean;
}

/** Label for the exploded hold: grouped by catalog part, human title, source line. */
export function partLabel(p: PartLike & Pick<BuildPart, "origin">): PartLabel {
  const title = humanGroupName(p);
  // Halves of a split build share one label: drop the side from the name.
  const name = p.card.display_name.replace(/\s*\((left|right|l|r)\)\s*$/i, "");
  const licence = p.card.licence_spdx && p.card.licence_spdx !== "unknown" ? ` · ${p.card.licence_spdx}` : "";
  const generated = p.origin === "user";
  return {
    key: `p:${title.toLowerCase()}`,
    title,
    detail: name.toLowerCase() === title.toLowerCase() ? "" : name,
    sub: generated ? "added by you" : `sourced part${licence}`,
    generated: false,
  };
}
