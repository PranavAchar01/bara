// Case finishes: what the shell is made of, beyond its colour. Each one is a
// real printable or cut material, drawn as a physical material: see-through
// finishes pass light (transmission) so the board and parts show inside,
// tinted by the case colour over the wall's thickness. One cached material per
// colour and finish, clarity and frost rounded so sliders reuse shaders.
import * as THREE from "three";
import { create } from "zustand";
import type { Color, Finish, FinishPreset, Material } from "../spec/types";

/**
 * A case look being tried in the panel (slider held, chip just picked), drawn
 * before the edit round-trips. Cleared when the engine applies or rejects it.
 */
export const useCasePreview = create<{ byId: Record<string, Color> }>(() => ({ byId: {} }));

export function previewCase(enclosureId: string, color: Color | null): void {
  useCasePreview.setState((s) => {
    const byId = { ...s.byId };
    if (color) byId[enclosureId] = color;
    else delete byId[enclosureId];
    return { byId };
  });
}

export interface FinishInfo {
  preset: FinishPreset;
  label: string;
  /** The real material it stands for, shown under the chip. */
  makes: string;
  /** Spec Material it reports (BOM, exports). */
  material: Material;
  seeThrough: boolean;
  clarity: number;
  frost: number;
}

export const FINISHES: FinishInfo[] = [
  { preset: "matte", label: "Matte", makes: "PLA", material: "plastic", seeThrough: false, clarity: 0, frost: 0.8 },
  { preset: "satin", label: "Satin", makes: "PETG", material: "plastic", seeThrough: false, clarity: 0, frost: 0.5 },
  { preset: "gloss", label: "Gloss", makes: "Moulded ABS", material: "plastic", seeThrough: false, clarity: 0, frost: 0.15 },
  { preset: "silk", label: "Silk", makes: "Silk PLA", material: "plastic", seeThrough: false, clarity: 0, frost: 0.3 },
  { preset: "frosted", label: "Frosted", makes: "Translucent PETG", material: "plastic", seeThrough: true, clarity: 0.85, frost: 0.7 },
  { preset: "clear", label: "Clear", makes: "Acrylic or resin", material: "glass", seeThrough: true, clarity: 0.96, frost: 0.05 },
  { preset: "smoke", label: "Smoke", makes: "Tinted acrylic", material: "glass", seeThrough: true, clarity: 0.8, frost: 0.08 },
  { preset: "metal", label: "Metal", makes: "Anodised aluminium", material: "metal", seeThrough: false, clarity: 0, frost: 0.4 },
];

/** The finish every shell starts in: clear, so the board and parts show through until someone picks another. */
export const DEFAULT_FINISH: FinishPreset = "clear";

export function finishInfo(preset: FinishPreset | undefined): FinishInfo {
  return FINISHES.find((f) => f.preset === preset) ?? FINISHES.find((f) => f.preset === DEFAULT_FINISH)!;
}

/** The finish a case shows: its own, else clear (the shell before anyone picks one). */
export function resolveFinish(f: Finish | undefined | null): Required<Finish> {
  const info = finishInfo(f?.preset);
  return { preset: info.preset, clarity: f?.clarity ?? info.clarity, frost: f?.frost ?? info.frost };
}

const step = (v: number) => Math.round(Math.min(1, Math.max(0, v)) * 50) / 50;
const cache = new Map<string, THREE.MeshPhysicalMaterial>();
const WHITE = new THREE.Color("#ffffff");

function make(hex: string, f: Required<Finish>): THREE.MeshPhysicalMaterial {
  const tint = new THREE.Color(hex);
  const frost = f.frost;
  switch (f.preset) {
    case "matte":
      return new THREE.MeshPhysicalMaterial({ color: tint, roughness: 0.6 + 0.35 * frost, metalness: 0, specularIntensity: 0.35 });
    case "gloss":
      return new THREE.MeshPhysicalMaterial({ color: tint, roughness: 0.05 + 0.4 * frost, metalness: 0, clearcoat: 1, clearcoatRoughness: 0.04 + 0.2 * frost, specularIntensity: 1 });
    case "silk":
      // Silk PLA: a pearly, almost metallic sheen that follows the layer lines.
      return new THREE.MeshPhysicalMaterial({
        color: tint,
        roughness: 0.18 + 0.4 * frost,
        metalness: 0.4,
        clearcoat: 0.5,
        clearcoatRoughness: 0.25,
        sheen: 0.8,
        sheenRoughness: 0.35,
        sheenColor: tint.clone().lerp(WHITE, 0.5),
      });
    case "frosted":
      // Translucent PETG: light passes but scatters; the case colour tints what is seen through it.
      return new THREE.MeshPhysicalMaterial({
        color: tint.clone().lerp(WHITE, 0.55),
        metalness: 0,
        roughness: 0.25 + 0.6 * frost,
        transmission: f.clarity,
        thickness: 2,
        ior: 1.57,
        attenuationColor: tint,
        attenuationDistance: 14,
        specularIntensity: 0.6,
      });
    case "clear":
      // Acrylic or resin: nearly glass, a faint tint in thick sections.
      return new THREE.MeshPhysicalMaterial({
        color: tint.clone().lerp(WHITE, 0.85),
        metalness: 0,
        roughness: 0.02 + 0.45 * frost,
        transmission: f.clarity,
        thickness: 3,
        ior: 1.49,
        attenuationColor: tint,
        attenuationDistance: 45,
        clearcoat: 1,
        clearcoatRoughness: 0.03,
        specularIntensity: 1,
      });
    case "smoke":
      // Tinted acrylic: dark and glossy, the inside shows when light gets in.
      return new THREE.MeshPhysicalMaterial({
        color: tint.clone().lerp(WHITE, 0.25),
        metalness: 0,
        roughness: 0.03 + 0.35 * frost,
        transmission: f.clarity,
        thickness: 3,
        ior: 1.49,
        attenuationColor: tint,
        // Dark, but the board still reads through a 3 mm wall.
        attenuationDistance: 10,
        clearcoat: 1,
        clearcoatRoughness: 0.04,
        specularIntensity: 1,
      });
    case "metal":
      // Anodised aluminium: coloured metal with a brushed (anisotropic) highlight.
      return new THREE.MeshPhysicalMaterial({ color: tint, metalness: 1, roughness: 0.2 + 0.4 * frost, anisotropy: 0.7, clearcoat: 0.15, clearcoatRoughness: 0.4 });
    default: {
      // Satin: a little sheen at grazing angles so the shell's shape shows against the floor.
      const rim = tint.clone().lerp(WHITE, 0.35);
      return new THREE.MeshPhysicalMaterial({
        color: tint,
        roughness: 0.3 + 0.4 * frost,
        metalness: 0,
        clearcoat: 0.2,
        clearcoatRoughness: 0.45,
        specularIntensity: 0.8,
        sheen: 0.35,
        sheenRoughness: 0.6,
        sheenColor: rim,
      });
    }
  }
}

/** The shell's material for a colour and finish (cached; never dispose the result). */
export function caseMaterial(hex: string, finish: Finish | undefined | null): THREE.MeshPhysicalMaterial {
  const f = resolveFinish(finish);
  const r = { ...f, clarity: step(f.clarity), frost: step(f.frost) };
  const key = `${hex.toLowerCase()}|${r.preset}|${r.clarity}|${r.frost}`;
  let m = cache.get(key);
  if (!m) {
    m = make(hex, r);
    m.userData.finish = r.preset;
    cache.set(key, m);
  }
  return m;
}

/** A CSS background that suggests the finish on a chip (no WebGL needed). */
export function finishSwatch(hex: string, preset: FinishPreset): string {
  const glossy = `linear-gradient(135deg, rgb(255 255 255 / 55%) 0%, rgb(255 255 255 / 0%) 38%)`;
  const checker = `repeating-conic-gradient(rgb(0 0 0 / 12%) 0 25%, transparent 0 50%) 0 0 / 8px 8px`;
  switch (preset) {
    case "matte":
      return hex;
    case "gloss":
      return `${glossy}, ${hex}`;
    case "silk":
      return `linear-gradient(120deg, ${hex} 0%, rgb(255 255 255 / 70%) 45%, ${hex} 70%), ${hex}`;
    case "frosted":
      return `linear-gradient(${hex}99, ${hex}99), ${checker}, #f4f4f1`;
    case "clear":
      return `${glossy}, linear-gradient(${hex}33, ${hex}33), ${checker}, #f4f4f1`;
    case "smoke":
      return `${glossy}, linear-gradient(${hex}cc, ${hex}cc), ${checker}, #f4f4f1`;
    case "metal":
      return `repeating-linear-gradient(90deg, rgb(255 255 255 / 14%) 0 1px, transparent 1px 3px), linear-gradient(160deg, rgb(255 255 255 / 45%), rgb(0 0 0 / 25%)), ${hex}`;
    default:
      return `linear-gradient(160deg, rgb(255 255 255 / 25%), rgb(0 0 0 / 8%)), ${hex}`;
  }
}

/**
 * How the shell is shown while building: clear (the default, so the board and parts show
 * through) or coloured in the palette. The simulation always shows it coloured.
 */
export const useShellView = create<{ clear: boolean; panel: boolean }>(() => ({ clear: true, panel: false }));

const solidCache = new Map<string, THREE.MeshPhysicalMaterial>();

/** Opaque moulded plastic in a palette colour: matte with a soft clearcoat, so it reads as a product. */
export function solidShell(hex: string): THREE.MeshPhysicalMaterial {
  const key = hex.toLowerCase();
  let m = solidCache.get(key);
  if (!m) {
    // The studio lights run a little hot, so the base colour is pulled down to land on the palette colour.
    const c = new THREE.Color(hex).multiplyScalar(0.84);
    m = new THREE.MeshPhysicalMaterial({
      color: c,
      roughness: 0.52,
      metalness: 0,
      clearcoat: 0.3,
      clearcoatRoughness: 0.55,
      specularIntensity: 0.55,
      sheen: 0.25,
      sheenRoughness: 0.7,
      sheenColor: c.clone().lerp(WHITE, 0.4),
    });
    m.userData.finish = "solid";
    solidCache.set(key, m);
  }
  return m;
}

const glassCache = new Map<string, THREE.MeshPhysicalMaterial>();

/** Screen glass tinted by the palette: glossy, faintly lit, so the screen reads as a display. */
export function screenGlass(hex: string): THREE.MeshPhysicalMaterial {
  const key = hex.toLowerCase();
  let m = glassCache.get(key);
  if (!m) {
    m = new THREE.MeshPhysicalMaterial({ color: new THREE.Color(hex), roughness: 0.08, metalness: 0, clearcoat: 1, clearcoatRoughness: 0.05, emissive: new THREE.Color(hex), emissiveIntensity: 0.18 });
    m.userData.finish = "solid";
    glassCache.set(key, m);
  }
  return m;
}

/** The shell colours of a build whose design step gave none: warm grey body, dark grey trim, near black buttons, maroon action buttons, pale green screen. */
export const DEFAULT_SHELL = { body: "#CFCBC0", trim: "#4A4D55", buttons: "#23252A", accent: "#A8325E", screen: "#B7D39A" } as const;
