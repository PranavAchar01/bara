// Build + firmware -> the device the simulator runs: its keys (where they sit in 3D and which
// keymap position each one is), displays, controllers, sensors and the parsed keymap.
import type { Build, BuildPart, Firmware } from "../spec/types";
import { elementPoses, type V3 } from "../three/layout";
import { isKeycapPart } from "../three/explode";
import {
  defaultKeymap,
  keymapFile,
  parseGadget,
  parseKconfig,
  parseKeymapSource,
  parseMatrixTransform,
  type EncoderBinding,
  type KeymapLayer,
} from "./firmware";

export interface SimKey {
  /** instance_id:element index; stable across reloads of the same build. */
  id: string;
  instanceId: string;
  side: string;
  element: number;
  /** Keycap centre in build space, mm. */
  position: V3;
  rotation: V3;
  yaw: number;
  w_u: number;
  h_u: number;
  thumb: boolean;
  /** Keymap position (index into each layer's bindings). */
  pos: number;
}

export interface SimDisplay {
  instanceId: string;
  side: string;
  label: string;
  width: number;
  height: number;
  position: V3;
}

export interface SimTarget {
  targetId: string;
  mcuInstanceId: string;
  side: string;
  label: string;
  role: "central" | "peripheral" | "single";
  binary: { name: string; bytes: number } | null;
}

export interface SimSensor {
  kind: string;
  instanceId: string | null;
  label: string;
}

export interface SimDevice {
  kind: "keyboard" | "gadget";
  name: string;
  framework: string;
  firmwareId: string;
  keymapPath: string | null;
  /** Where the layers came from: the firmware's own keymap, or the board's default when the file is a stub. */
  keymapSource: "firmware" | "default" | "none";
  /** How key positions were matched to keymap positions. */
  mapping: "transform" | "physical";
  keys: SimKey[];
  layers: KeymapLayer[];
  encoders: EncoderBinding[];
  displays: SimDisplay[];
  targets: SimTarget[];
  sensors: SimSensor[];
  config: Record<string, string>;
  updateMs: number;
  pins: { instanceId: string; signal: string; mcuPin: string }[];
  /** Plain notes for the console: what was read and what was assumed. */
  notes: string[];
}

function sideOf(p: BuildPart): string {
  return String(p.side ?? "none");
}

/** One layout part per side carries the keys: keycaps when the build has them, else the switches. */
function keyParts(parts: BuildPart[]): BuildPart[] {
  const layout = parts.filter((p) => p.placement.mode === "layout" && p.quantity > 0);
  const bySide = new Map<string, BuildPart>();
  for (const p of layout) {
    const cur = bySide.get(sideOf(p));
    if (!cur || (isKeycapPart(p) && !isKeycapPart(cur))) bySide.set(sideOf(p), p);
  }
  const order = (s: string) => (s === "left" ? 0 : s === "right" ? 2 : 1);
  return [...bySide.values()].sort((a, b) => order(sideOf(a)) - order(sideOf(b)));
}

interface RawKey extends Omit<SimKey, "pos"> {
  matrix: number[] | null;
  rowGuess: number;
}

function rawKeys(build: Build): RawKey[] {
  const out: RawKey[] = [];
  for (const p of keyParts(build.parts)) {
    const layout = build.layouts?.find((l) => l.layout_id === p.placement.layout_id);
    const poses = elementPoses(p.placement, p.quantity, layout);
    const byIndex = new Map((layout?.keys ?? []).map((k) => [k.i, k]));
    for (const e of poses) {
      const k = byIndex.get(e.index);
      out.push({
        id: `${p.instance_id}:${e.index}`,
        instanceId: p.instance_id,
        side: sideOf(p),
        element: e.index,
        position: e.position,
        rotation: e.rotation,
        yaw: e.yaw,
        w_u: e.w_u,
        h_u: e.h_u,
        thumb: false,
        matrix: k?.matrix && k.matrix.length >= 2 ? k.matrix : null,
        rowGuess: Math.round(k?.y_u ?? 0),
      });
    }
  }
  return out;
}

/** Row of a key within its half: matrix row folded per half (split boards number the right half's rows after the left's). */
function rowsOf(keys: RawKey[]): number[] {
  const perSide = new Map<string, number>();
  for (const k of keys) if (k.matrix) perSide.set(k.side, Math.min(perSide.get(k.side) ?? Infinity, k.matrix[0]));
  return keys.map((k) => (k.matrix ? k.matrix[0] - (perSide.get(k.side) ?? 0) : k.rowGuess));
}

/** Keymap order when the firmware has no transform: row by row, left to right across both halves. */
function physicalOrder(keys: RawKey[]): number[] {
  const rows = rowsOf(keys);
  const idx = keys.map((_, i) => i);
  idx.sort((a, b) => rows[a] - rows[b] || keys[a].position[0] - keys[b].position[0]);
  return idx;
}

/** Keymap order from the firmware's matrix transform: binding i is RC(row, col); right half columns follow the left's. */
function transformOrder(keys: RawKey[], transform: [number, number][], colOffset: number): number[] | null {
  if (!keys.every((k) => k.matrix)) return null;
  const rows = rowsOf(keys);
  const at = new Map<string, number>();
  keys.forEach((k, i) => {
    const col = (k.matrix as number[])[1] + (k.side === "right" ? colOffset : 0);
    at.set(`${rows[i]},${col}`, i);
  });
  const order: number[] = [];
  for (const [r, c] of transform) {
    const i = at.get(`${r},${c}`);
    if (i === undefined) return null;
    order.push(i);
  }
  return new Set(order).size === keys.length ? order : null;
}

function displays(build: Build): SimDisplay[] {
  return build.parts
    .filter((p) => /^disp:/.test(p.part_id) || /display/.test(String(p.card.primary_function ?? "")))
    .map((p) => {
      const res = /(\d{2,3})x(\d{2,3})/.exec(`${p.part_id} ${p.card.display_name}`);
      return {
        instanceId: p.instance_id,
        side: sideOf(p),
        label: p.label ?? p.card.display_name,
        width: res ? Number(res[1]) : 128,
        height: res ? Number(res[2]) : 32,
        position: [p.placement.position_mm[0] ?? 0, p.placement.position_mm[1] ?? 0, p.placement.position_mm[2] ?? 0],
      };
    });
}

function targets(build: Build, fw: Firmware): SimTarget[] {
  const list = fw.targets ?? [];
  const bins = fw.compile.binaries ?? [];
  if (!list.length) {
    const mcu = build.parts.find((p) => /^mod:/.test(p.part_id) && /mcu|controller/.test(`${p.slot_id ?? ""} ${p.card.primary_function ?? ""}`));
    return mcu ? [{ targetId: "main", mcuInstanceId: mcu.instance_id, side: sideOf(mcu), label: "Main", role: "single", binary: null }] : [];
  }
  // ZMK: the half labelled central holds the host link; without a label, the left half does
  const central = list.find((t) => /central/i.test(t.label ?? "")) ?? list.find((t) => t.side === "left");
  return list.map((t, i): SimTarget => {
    const bin = bins.find((b) => b.url.includes(t.target_id)) ?? bins[i] ?? null;
    return {
      targetId: t.target_id,
      mcuInstanceId: t.mcu_instance_id,
      side: String(t.side ?? "none"),
      label: t.label ?? t.target_id,
      role: list.length === 1 ? "single" : t === central ? "central" : "peripheral",
      binary: bin ? { name: bin.url.split("/").pop() ?? bin.asset_id, bytes: bin.bytes ?? 0 } : null,
    };
  });
}

/**
 * The simulated device. `keymapOverride` is a keymap file the user loaded in place of the build's
 * (path and text), so a hand-edited .keymap or keymap.c can be tried on the same hardware.
 */
export function loadDevice(build: Build, keymapOverride?: { path: string; content: string } | null): SimDevice | null {
  const fw = build.firmware;
  if (!fw) return null;
  const notes: string[] = [];
  const keys0 = rawKeys(build);
  const kind: SimDevice["kind"] = keys0.length > 0 ? "keyboard" : "gadget";
  const config: Record<string, string> = {};
  for (const f of fw.files) if (f.language === "kconfig" || f.path.endsWith(".conf")) Object.assign(config, parseKconfig(f.content ?? ""));
  const pins = (fw.pin_map ?? []).map((p) => ({ instanceId: p.instance_id, signal: p.signal, mcuPin: p.mcu_pin }));

  let keys: SimKey[] = [];
  let layers: KeymapLayer[] = [];
  let encoders: EncoderBinding[] = [];
  let keymapSource: SimDevice["keymapSource"] = "none";
  let mapping: SimDevice["mapping"] = "physical";
  const file = keymapOverride ?? (() => {
    const f = keymapFile(fw);
    return f ? { path: f.path, content: f.content ?? "" } : null;
  })();
  if (kind === "keyboard") {
    const transformSrc = fw.files.find((f) => /matrix-transform/.test(f.content ?? ""))?.content ?? "";
    const transform = transformSrc ? parseMatrixTransform(transformSrc) : null;
    const offset = Number(/col-offset\s*=\s*<\s*(\d+)\s*>/.exec(fw.files.map((f) => f.content ?? "").join("\n"))?.[1] ?? NaN);
    const leftCols = Math.max(0, ...keys0.filter((k) => k.side !== "right" && k.matrix).map((k) => (k.matrix as number[])[1] + 1));
    let order = transform ? transformOrder(keys0, transform, Number.isFinite(offset) ? offset : leftCols) : null;
    if (order) mapping = "transform";
    else {
      if (transform) notes.push("The matrix transform does not cover every key on the board; keys are matched to the keymap by position instead.");
      order = physicalOrder(keys0);
    }
    // the bottom row of each half is the thumb cluster
    const rows = rowsOf(keys0);
    const lastRow = new Map<string, number>();
    keys0.forEach((k, i) => lastRow.set(k.side, Math.max(lastRow.get(k.side) ?? 0, rows[i])));
    keys = order.map((i, pos) => {
      const { matrix: _m, rowGuess: _r, ...k } = keys0[i];
      return { ...k, thumb: rows[i] === lastRow.get(k.side) && rows[i] > 0, pos };
    });
    const parsed = file ? parseKeymapSource(file.path, file.content) : { layers: [], encoders: [] };
    if (parsed.layers.some((l) => l.bindings.length > 0)) {
      layers = parsed.layers;
      encoders = parsed.encoders;
      keymapSource = "firmware";
      const n = layers[0].bindings.length;
      if (n !== keys.length) notes.push(`${file?.path} binds ${n} positions; the board has ${keys.length} keys. Unbound keys do nothing.`);
    } else {
      const d = defaultKeymap(keys.length, keys.map((k) => k.thumb));
      layers = d.layers;
      encoders = d.encoders;
      keymapSource = "default";
      notes.push(
        file
          ? `${file.path} has no bindings in it (a template stub), so the board runs ${fw.framework.toUpperCase()}'s default ${keys.length === 42 ? "Corne " : ""}keymap.`
          : `No keymap file in the firmware, so the board runs the default keymap.`,
      );
    }
  }
  const gadget = parseGadget(fw);
  const sensors: SimSensor[] = gadget.sensors.map((s) => {
    const part = build.parts.find((p) => p.part_id.toLowerCase().includes(s));
    return { kind: s, instanceId: part?.instance_id ?? null, label: part?.card.display_name ?? s.toUpperCase() };
  });
  const encCount = Object.keys(config).some((k) => k === "CONFIG_EC11") ? Math.max(1, encoders.length) : gadget.encoders;
  for (let i = encoders.length; i < encCount; i++) encoders.push({ cw: "C_VOL_UP", ccw: "C_VOL_DN" });
  if (fw.compile.binaries?.length)
    notes.push(
      `The compiled images (${fw.compile.binaries.map((b) => b.url.split("/").pop()).join(", ")}) are for the ${fw.framework === "zmk" ? "nRF52840" : fw.framework === "qmk" ? "ATmega32U4" : "target"} MCU, which no browser emulator runs; the simulator runs the same ${kind === "keyboard" ? "keymap and config" : "code's peripherals and timing"} instead.`,
    );
  return {
    kind,
    name: build.prompt,
    framework: fw.framework,
    firmwareId: fw.firmware_id,
    keymapPath: file?.path ?? null,
    keymapSource,
    mapping,
    keys,
    layers,
    encoders,
    displays: displays(build),
    targets: targets(build, fw),
    sensors,
    config,
    updateMs: gadget.updateMs,
    pins,
    notes,
  };
}
