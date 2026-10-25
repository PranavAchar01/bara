// The play surface of one build, and the person's own arrangement of it. The engine decides which
// controls exist (always real inputs of the build) and how each output shows; this file holds only
// what the person changes on top: hide, reorder, rename, the lead control and the values they set on
// sensors. The arrangement is kept per build in the browser, and every id in it is checked against
// the surface, so a stale or edited entry can never conjure a control the device does not have.
import type { ControlKind, OutputShow, SimIo, Surface, SurfaceControl, SurfaceOp } from "./remote";

export interface Layout {
  hidden: string[];
  /** Control ids in the person's order; controls not listed follow in the surface's own order. */
  order: string[];
  names: Record<string, string>;
  lead: string | null;
  /** Last value set on each sensor. */
  values: Record<string, number>;
}

export const emptyLayout = (): Layout => ({ hidden: [], order: [], names: {}, lead: null, values: {} });

const KEY = (buildId: string) => `bara.sim.layout.${buildId}`;
const NAME_MAX = 40;

/** UI copy: plain printable text, no dashes as punctuation, bounded. */
export function cleanName(text: string): string {
  return text
    .replace(/[–—]/g, ",")
    .replace(/[^\x20-\x7E°µ]/g, "")
    .replace(/\s+/g, " ")
    .replace(/\s+,/g, ",")
    .trim()
    .slice(0, NAME_MAX)
    .trim();
}

export function loadLayout(buildId: string, surface: Surface | null): Layout {
  try {
    const raw = window.localStorage.getItem(KEY(buildId));
    const data: unknown = raw ? JSON.parse(raw) : null;
    return surface ? sanitize(data, surface) : emptyLayout();
  } catch {
    return emptyLayout();
  }
}

export function saveLayout(buildId: string, layout: Layout): void {
  try {
    window.localStorage.setItem(KEY(buildId), JSON.stringify(layout));
  } catch {
    // storage can be blocked; the arrangement then lasts for this visit only
  }
}

/** Keep only what refers to real controls of this surface. */
export function sanitize(data: unknown, surface: Surface): Layout {
  const ids = new Set(surface.controls.map((c) => c.input_id));
  const o = (data && typeof data === "object" ? data : {}) as Record<string, unknown>;
  const list = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === "string" && ids.has(x)) : []);
  const names: Record<string, string> = {};
  if (o.names && typeof o.names === "object") {
    for (const [k, v] of Object.entries(o.names as Record<string, unknown>)) {
      const n = typeof v === "string" ? cleanName(v) : "";
      if (ids.has(k) && n) names[k] = n;
    }
  }
  const values: Record<string, number> = {};
  if (o.values && typeof o.values === "object") {
    for (const [k, v] of Object.entries(o.values as Record<string, unknown>)) {
      const c = surface.controls.find((x) => x.input_id === k);
      if (c && c.kind === "sensor" && typeof v === "number" && Number.isFinite(v)) values[k] = clampTo(c, v);
    }
  }
  const lead = typeof o.lead === "string" && ids.has(o.lead) ? o.lead : null;
  return { hidden: list(o.hidden), order: [...new Set(list(o.order))], names, lead, values };
}

export function clampTo(c: SurfaceControl, v: number): number {
  const lo = c.min ?? 0;
  const hi = c.max ?? 1;
  return Math.min(hi, Math.max(lo, v));
}

export interface Row extends SurfaceControl {
  hidden: boolean;
  isLead: boolean;
}

/** Every control in display order, with the person's names applied; hidden ones are flagged, not dropped. */
export function resolveRows(surface: Surface, layout: Layout): Row[] {
  const lead = layout.lead ?? surface.lead;
  const base = new Map(surface.controls.map((c) => [c.input_id, c]));
  const ordered = [...layout.order.filter((id) => base.has(id)), ...surface.controls.map((c) => c.input_id).filter((id) => !layout.order.includes(id))];
  // without a chosen order the lead control comes first
  if (!layout.order.length && lead && base.has(lead)) ordered.sort((a, b) => Number(b === lead) - Number(a === lead));
  return ordered.map((id) => {
    const c = base.get(id) as SurfaceControl;
    return { ...c, label: layout.names[id] ?? c.label, hidden: layout.hidden.includes(id), isLead: id === lead };
  });
}

/** Rows grouped under the group names the surface gave, in order of first appearance. */
export function groupRows(rows: Row[]): { group: string; rows: Row[] }[] {
  const out: { group: string; rows: Row[] }[] = [];
  for (const r of rows) {
    const g = out.find((x) => x.group === r.group);
    if (g) g.rows.push(r);
    else out.push({ group: r.group, rows: [r] });
  }
  return out;
}

export function setHidden(layout: Layout, id: string, hidden: boolean): Layout {
  const rest = layout.hidden.filter((x) => x !== id);
  return { ...layout, hidden: hidden ? [...rest, id] : rest };
}

export function rename(layout: Layout, id: string, name: string): Layout {
  const n = cleanName(name);
  const names = { ...layout.names };
  if (n) names[id] = n;
  else delete names[id];
  return { ...layout, names };
}

export function move(layout: Layout, surface: Surface, id: string, by: -1 | 1): Layout {
  const ids = resolveRows(surface, layout).map((r) => r.input_id);
  const i = ids.indexOf(id);
  const j = i + by;
  if (i < 0 || j < 0 || j >= ids.length) return layout;
  [ids[i], ids[j]] = [ids[j], ids[i]];
  return { ...layout, order: ids };
}

export function setValue(layout: Layout, c: SurfaceControl, v: number): Layout {
  return { ...layout, values: { ...layout.values, [c.input_id]: clampTo(c, v) } };
}

/** Apply the agent's surface changes. The engine has checked them; they are checked again here. */
export function applyOps(layout: Layout, surface: Surface, ops: SurfaceOp[]): { layout: Layout; sensorSets: { id: string; value: number }[] } {
  let next = layout;
  const sets: { id: string; value: number }[] = [];
  for (const op of ops) {
    const c = surface.controls.find((x) => x.input_id === op.input_id);
    if (!c) continue;
    if (op.op === "show") next = setHidden(next, c.input_id, false);
    else if (op.op === "hide") next = setHidden(next, c.input_id, true);
    else if (op.op === "rename" && op.label) next = rename(next, c.input_id, op.label);
    else if (op.op === "lead") next = { ...next, lead: c.input_id };
    else if (op.op === "set" && c.kind === "sensor" && typeof op.value === "number") {
      const v = clampTo(c, op.value);
      next = setValue(next, c, v);
      sets.push({ id: c.input_id, value: v });
    }
  }
  return { layout: next, sensorSets: sets };
}

/** Sensor value as text with its unit: "42 %", "21.5 °C". */
export function withUnit(c: SurfaceControl, v: number): string {
  const span = (c.max ?? 1) - (c.min ?? 0);
  const text = span >= 100 ? String(Math.round(v)) : v.toFixed(span >= 10 ? 1 : 2).replace(/\.?0+$/, "");
  return c.unit ? `${text} ${c.unit}` : text;
}

const CONTROL_OF: Record<string, ControlKind> = { key: "key", mkey: "key", button: "button", switch: "toggle", encoder: "knob", axis: "slider", pot: "slider", sensor: "slider" };
const GROUP_OF: Record<string, string> = { key: "Keys", button: "Buttons", switch: "Switches", encoder: "Knobs", axis: "Sticks", sensor: "Measurements" };
const SHOW_OF: Record<string, OutputShow> = { display: "screen", led: "led", tone: "buzzer", motor: "motor", serial: "console", hid: "console" };

const GENERIC_LABEL = /^(adjustment|adjust|setting|control|input|knob|dial|slider|axis|channel|value|menu selection)(\s*\d+)?(\s+press)?$/i;

/** A placeholder rather than a name: empty, or a word like "Adjustment 2". */
export function isGenericLabel(label: string): boolean {
  const t = label.trim();
  return !t || GENERIC_LABEL.test(t);
}

function derivedLabel(c: SurfaceControl, index: number, count: number): string {
  const n = count > 1 ? ` ${index + 1}` : "";
  if (c.kind === "sensor") return c.unit ? `Sensor reading${n} (${c.unit})` : `Sensor reading${n}`;
  if (c.kind === "axis") {
    const ax = /\.([xy])$/.exec(c.input_id);
    return ax ? `Joystick ${ax[1].toUpperCase()} axis (%)` : `Potentiometer position${n} (%)`;
  }
  if (c.kind === "encoder") return `Rotary encoder position${n} (steps)`;
  if (c.kind === "switch") return `Switch position${n} (on/off)`;
  if (c.input_id.endsWith(".press")) return `Encoder push switch${n} (pressed)`;
  return `Push button${n} (pressed)`;
}

/** Replace placeholder control labels with a standardized label and unit, whatever produced them. */
export function fixLabels(surface: Surface): Surface {
  const groupOf = (c: SurfaceControl) => `${c.kind}:${c.input_id.endsWith(".press")}`;
  const sameGroup = (c: SurfaceControl) => surface.controls.filter((x) => groupOf(x) === groupOf(c));
  const controls = surface.controls.map((c) => {
    if (!isGenericLabel(c.label)) return c;
    const group = sameGroup(c);
    return { ...c, label: derivedLabel(c, group.indexOf(c), group.length) };
  });
  return { ...surface, controls };
}

/** The surface read straight off the plan, for when the engine's spec cannot be had. */
export function fallbackSurface(io: SimIo): Surface {
  const controls: SurfaceControl[] = io.inputs.map((i) => ({
    input_id: i.id,
    kind: i.kind,
    control: i.kind === "axis" && /\.[xy]$/.test(i.id) ? "stick" : (CONTROL_OF[i.kind] ?? "button"),
    label: cleanName(i.label) || i.id,
    unit: i.kind === "sensor" ? (i.unit ?? "") : "",
    group: GROUP_OF[i.kind] ?? "Controls",
    instance_id: i.instance_id,
    index: i.index,
    min: i.min,
    max: i.max,
    default: i.default,
  }));
  const outputs = io.outputs.map((o) => ({ output_id: o.id, kind: o.kind, show: SHOW_OF[o.kind] ?? "console", label: cleanName(o.label) }));
  return fixLabels({ controls, outputs, lead: controls[0]?.input_id ?? "", sig: "client", by: "parts" });
}
