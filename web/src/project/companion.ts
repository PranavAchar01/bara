// A new device made for the one on screen ("add a mouse to this keyboard", "connect a mouse", "make
// a matching mouse"): its own canvas tab right after the parent's, both devices standing together on
// it, and the parent's look carried over. The engine writes the new device's prompt with the
// parent's colours, case material, finish and connector in it (POST /v1/intent with parent_style);
// once the new device is built its shell gets the parent's exact palette.
//
// It also says what each device on a shared canvas is (`kind`) and how big it is (`bbox_mm`), for
// the camera layout to arrange them by (sceneDevices).
import { addCompanionCanvas, canvasState } from "../state/canvases";
import { useApp, type AppState } from "../state/store";
import type { BBox, Build, ShellPalette } from "../spec/types";
import { linkWhenBuilt } from "./awaiting";
import { deviceKindOf, isDeviceKind, type DeviceKind } from "./deviceKind";

export { deviceKindOf, type DeviceKind } from "./deviceKind";

/** A build's kind: the engine's word for it first, then its spec's device class, then its prompt. */
export function kindOfBuild(build: Build | null | undefined, given?: string | null): DeviceKind {
  if (isDeviceKind(given)) return given;
  return deviceKindOf(build?.spec?.device_class?.replace(/_/g, " ")) ?? deviceKindOf(build?.prompt) ?? "device";
}

/** What the new device takes after: what the parent is, its shell colours, case material and finish, connector. */
export interface ParentStyle {
  device: string;
  kind: DeviceKind;
  palette: Partial<ShellPalette>;
  material: string | null;
  finish: string | null;
  connector: string | null;
}

const ROLES = ["body", "trim", "buttons", "accent", "screen"] as const;
const HEX = /^#[0-9a-f]{3,8}$/i;

/** The parent's look, read from its build. */
export function styleOf(build: Build): ParentStyle {
  const palette: Partial<ShellPalette> = {};
  const fin = build.scene?.finish?.palette ?? {};
  for (const r of ROLES) if (typeof fin[r] === "string" && HEX.test(fin[r] as string)) palette[r] = fin[r];
  const shell = build.enclosures.find((e) => e.kind !== "none");
  if (!palette.body && shell?.color?.hex && HEX.test(shell.color.hex)) palette.body = shell.color.hex;
  const material = shell?.color?.material ?? shell?.material ?? null;
  const preset = shell?.color?.finish?.preset ?? null;
  // the parts first, then what was asked for ("a wireless keyboard")
  const text = [build.prompt, ...build.parts.map((p) => `${p.card.display_name} ${p.card.primary_function ?? ""} ${p.label ?? ""}`)].join(" | ").toLowerCase();
  const wired = /usb[\s-]?c\b|type[\s-]?c\b/.test(text) ? "USB-C" : /\busb\b/.test(text) ? "USB" : null;
  const radio = /bluetooth|\bble\b|nrf52|esp32|wireless/.test(text) ? "Bluetooth" : null;
  const kind = kindOfBuild(build);
  return {
    device: kind !== "device" ? kind : (build.spec?.device_class?.replace(/_/g, " ") ?? "device"),
    kind,
    palette,
    material: material && material !== "unknown" ? material : null,
    finish: preset && preset !== "unknown" ? preset : null,
    connector: radio && wired ? `${radio} and ${wired}` : (radio ?? wired),
  };
}

/** What the engine answers for a line over an open device (POST /v1/intent). */
export interface IntentRead {
  kind: string;
  thing: string | null;
  prompt: string;
  note?: string;
  device_kind?: string | null;
}

/** Palettes to put on a companion's shell once it is built, by canvas id. */
const pendingPalette = new Map<string, Partial<ShellPalette>>();

function title(thing: string): string {
  const t = thing.trim();
  return t ? t[0].toUpperCase() + t.slice(1) : "New device";
}

/**
 * The new device's canvas: a tab right after the parent's, switched to, with both devices on it,
 * named for the new device and marked as pairing with the parent. Returns the new canvas id; the
 * caller starts its build there.
 */
export function addDeviceCanvas(read: { thing: string | null; device_kind?: string | null; prompt: string }, parent: ParentStyle | null): string {
  const from = useApp.getState().activeCanvas;
  const given = isDeviceKind(read.device_kind) ? read.device_kind : null;
  const kind = given ?? deviceKindOf(read.thing) ?? deviceKindOf(read.prompt) ?? "device";
  const id = addCompanionCanvas({ name: title(read.thing ?? kind), kind, pairsWith: from });
  if (parent && Object.keys(parent.palette).length) pendingPalette.set(id, parent.palette);
  linkWhenBuilt(id);
  return id;
}

/** The palette still waiting for this canvas's device, taken (it is applied once). */
export function takePendingPalette(canvasId: string): Partial<ShellPalette> | null {
  const p = pendingPalette.get(canvasId) ?? null;
  pendingPalette.delete(canvasId);
  return p;
}

/**
 * Watches for a companion finishing its build on the open canvas and puts the parent's colours on its
 * shell. `apply` sends the palette edit (net/client applyEdit); returns a stop function.
 */
export function startStyleInherit(apply: (palette: Partial<ShellPalette>) => void): () => void {
  return useApp.subscribe((s) => {
    if (!pendingPalette.size || s.build?.status !== "done" || s.replaying) return;
    const p = takePendingPalette(s.activeCanvas);
    if (p) apply(p);
  });
}

/** One device on a shared canvas, for the camera layout. */
export interface LayoutDevice {
  canvasId: string;
  buildId: string | null;
  name: string;
  kind: DeviceKind;
  /** The device's assembled bounding box in its own frame (mm, x right, y back, z up); null until built. */
  bbox_mm: BBox | null;
  /** The canvas whose device this one was made for, if any. */
  pairsWith: string | null;
  /** The device whose canvas is open (it stays at its origin). */
  active: boolean;
}

/** Every device standing on the open canvas: the open one and its companions, in tab order. */
export function sceneDevices(s: AppState): LayoutDevice[] {
  const scene = new Set([s.activeCanvas, ...s.companions]);
  return s.canvases
    .filter((m) => scene.has(m.id))
    .map((m) => {
      const c = canvasState(s, m.id);
      const b = c?.build ?? null;
      return {
        canvasId: m.id,
        buildId: b?.build_id ?? null,
        name: m.name ?? b?.prompt ?? "New canvas",
        kind: kindOfBuild(b, m.kind),
        bbox_mm: b?.scene?.assembly_bbox_mm ?? null,
        pairsWith: m.pairsWith ?? null,
        active: m.id === s.activeCanvas,
      };
    });
}
