// Studio material presets (render recipe 2.5). One shared instance per
// preset + colour, so 100 parts compile a handful of shader variants.
import * as THREE from "three";
import type { BuildPart } from "../spec/types";
import { layerOf } from "./explode";

export type Preset = "keycap" | "case" | "pcb" | "switch" | "module" | "metal" | "glossy" | "battery" | "plastic";

const cache = new Map<string, THREE.MeshStandardMaterial>();

function make(preset: Preset, hex: string): THREE.MeshStandardMaterial {
  const color = new THREE.Color(hex);
  switch (preset) {
    case "keycap": {
      const sheen = color.clone().lerp(new THREE.Color("#ffffff"), 0.2);
      return new THREE.MeshPhysicalMaterial({ color, roughness: 0.62, metalness: 0, sheen: 0.15, sheenRoughness: 0.8, sheenColor: sheen, specularIntensity: 0.6 });
    }
    case "case": {
      // Clear moulded plastic: the shell is always see-through, the colour only a faint tint,
      // so the board and parts inside read through it like a transparent handheld.
      const tint = color.clone().lerp(new THREE.Color("#EEF3F7"), 0.85);
      return new THREE.MeshPhysicalMaterial({ color: tint, roughness: 0.08, metalness: 0, clearcoat: 1, clearcoatRoughness: 0.05, specularIntensity: 1, transparent: true, opacity: 1, depthWrite: false });
    }
    case "pcb":
      return new THREE.MeshPhysicalMaterial({ color, roughness: 0.45, metalness: 0, clearcoat: 0.35, clearcoatRoughness: 0.3 });
    case "switch":
      return new THREE.MeshStandardMaterial({ color, roughness: 0.5, metalness: 0 });
    case "metal":
      return new THREE.MeshStandardMaterial({ color, roughness: 0.35, metalness: 1 });
    case "glossy":
      return new THREE.MeshPhysicalMaterial({ color, roughness: 0.12, metalness: 0, clearcoat: 1, clearcoatRoughness: 0.05 });
    case "battery":
      return new THREE.MeshStandardMaterial({ color, roughness: 0.38, metalness: 0.55 });
    case "module":
      return new THREE.MeshStandardMaterial({ color, roughness: 0.48, metalness: 0.05 });
    default:
      return new THREE.MeshPhysicalMaterial({ color, roughness: 0.42, metalness: 0, clearcoat: 0.15, clearcoatRoughness: 0.5, specularIntensity: 0.8 });
  }
}

export function presetMaterial(preset: Preset, hex: string): THREE.MeshStandardMaterial {
  const key = `${preset}:${hex.toLowerCase()}`;
  let m = cache.get(key);
  if (!m) {
    m = make(preset, hex);
    cache.set(key, m);
  }
  return m;
}

/** Material preset for a part, from its colour's material and its layer. */
export function presetFor(part: Pick<BuildPart, "part_id" | "card" | "label" | "color">): Preset {
  const mat = part.color?.material;
  if (mat === "metal") return "metal";
  if (mat === "glass") return "glossy";
  const t = `${part.part_id} ${part.card.display_name} ${part.card.primary_function ?? ""}`.toLowerCase();
  if (/trackball|\bball\b/.test(t)) return "glossy";
  if (/^knob:|\bknob\b/.test(t)) return "metal";
  if (/screw|standoff|stabili[sz]er|fastener/.test(t)) return "metal";
  switch (layerOf(part)) {
    case "keycaps":
      return "keycap";
    case "switches":
      return "switch";
    case "pcb":
      return "pcb";
    case "plate":
      return /fr4|pcb/.test(t) ? "pcb" : /alu|steel|brass|metal/.test(t) ? "metal" : "plastic";
    case "case":
      return "case";
    case "under":
      return /bat|lipo/.test(t) ? "battery" : "module";
    default:
      return "module";
  }
}

/** Default colours by catalog prefix, used when a part has no colour of its own. */
export function defaultColor(part: Pick<BuildPart, "part_id" | "card" | "color">): string {
  const id = part.part_id;
  if (part.color?.hex) return part.color.hex;
  if (id.startsWith("cap:")) return "#ECE9E1";
  if (id.startsWith("knob:")) return "#C9CCD1";
  if (id.startsWith("ball:")) return "#C8302A";
  if (id.startsWith("sw:")) return /brown/.test(id) ? "#7A5236" : /red/.test(id) ? "#B8423A" : "#2E3034";
  if (String(part.card.kind) === "pcb") return "#1F3D2B";
  if (/plate/.test(id)) return /fr4/.test(id) ? "#1F3D2B" : "#8E949A";
  if (id.startsWith("mod:")) return "#1E2A3F";
  if (id.startsWith("disp:")) return "#15171A";
  if (id.startsWith("bat:")) return "#B9BCC0";
  if (id.startsWith("cable:")) return "#2A2C2E";
  return "#4A4F55";
}

/**
 * Parts whose look is the brief's (keycaps, knobs, trackballs): their GLBs
 * carry one flat material, so they always take the studio preset in the
 * part's colour. Everything else keeps the materials its GLB carries.
 */
export function usesPreset(preset: Preset): boolean {
  return preset === "keycap" || preset === "glossy" || preset === "metal";
}

/** Copy of a GLB material with a new base colour (keeps its roughness and metalness). */
const tintCache = new Map<string, THREE.MeshStandardMaterial>();
export function tinted(src: THREE.MeshStandardMaterial, hex: string): THREE.MeshStandardMaterial {
  const key = `${src.uuid}:${hex.toLowerCase()}`;
  let m = tintCache.get(key);
  if (!m) {
    m = src.clone();
    m.color = new THREE.Color(hex);
    m.map = null;
    tintCache.set(key, m);
  }
  return m;
}

/** Translucent copy for placeholders (SPEC 11.4: missing assets draw as translucent boxes). */
const ghostCache = new Map<string, THREE.MeshStandardMaterial>();
export function ghost(src: THREE.MeshStandardMaterial, opacity: number): THREE.MeshStandardMaterial {
  const key = `${src.uuid}:${opacity}`;
  let m = ghostCache.get(key);
  if (!m) {
    m = src.clone();
    m.transparent = true;
    m.opacity = opacity;
    m.depthWrite = true;
    ghostCache.set(key, m);
  }
  return m;
}

/** Placeholder look for parts with no model: a faint neutral shell, clearly not the part. */
const placeholderMat = new THREE.MeshStandardMaterial({ color: "#C3C7CD", roughness: 0.7, metalness: 0, transparent: true, opacity: 0.32, depthWrite: false });
export function placeholderMaterial(): THREE.MeshStandardMaterial {
  return placeholderMat;
}
