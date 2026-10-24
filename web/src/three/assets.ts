// GLB loading (SPEC 3.2): one load per URL, converted once to build space
// (scale 1000, then +90 deg about X). Meshes are merged per material so a
// part keeps the PBR materials its GLB carries (KiCad copper, mask, silk,
// component bodies) and still draws as a few instanced meshes. Failures
// resolve to null so the caller draws the bbox placeholder; one bad asset
// never blocks the scene.
import { useEffect, useState } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { MeshoptDecoder } from "three/examples/jsm/libs/meshopt_decoder.module.js";
import { mergeGeometries } from "three/examples/jsm/utils/BufferGeometryUtils.js";
import type { AssetRef } from "../spec/types";

export interface MeshGroup {
  geometry: THREE.BufferGeometry;
  material: THREE.MeshStandardMaterial;
  /** Vertex count, used to find the dominant material for tinting. */
  weight: number;
}

export interface LoadedModel {
  /** Root already converted to build space (mm, Z up). */
  root: THREE.Object3D;
  /** One merged geometry per material, in build space, for instancing. */
  groups: MeshGroup[];
  /** All meshes merged (position + normal only), for hulls and outlines. */
  merged: THREE.BufferGeometry | null;
  bbox: THREE.Box3;
  /** Board models: one box per footprint node (refdes), in build space, for hover. */
  footprints: FootprintBox[];
}

export interface FootprintBox {
  ref: string;
  box: THREE.Box3;
}

/** KiCad reference designators (SW3, U1, USB-UART1, LED3A); not OpenCASCADE labels. */
const REFDES = /^[A-Z][A-Za-z0-9]*([_-][A-Za-z0-9]+)*\d+[A-Za-z]?$/;

/** Nearest refdes-named node at or above `o`, the footprint a mesh belongs to. */
function footprintOf(o: THREE.Object3D | null): string | null {
  for (let n = o; n; n = n.parent) if (REFDES.test(n.name)) return n.name;
  return null;
}

const cache = new Map<string, Promise<LoadedModel | null>>();
const loader = new GLTFLoader();
// Meshopt buffers decode in workers, so a large board never stalls orbiting or the UI.
try {
  const n = Math.min(4, Math.max(1, (navigator.hardwareConcurrency || 2) >> 1));
  // useWorkers is in the decoder module but missing from its type definitions.
  if (n > 1) (MeshoptDecoder as typeof MeshoptDecoder & { useWorkers: (count: number) => void }).useWorkers(n);
} catch {
  // main-thread decoding
}
loader.setMeshoptDecoder(MeshoptDecoder);

export type BoardLayer = "mask" | "silk" | "pad" | "copper" | "body";

/** Layer of a material in a kicad-cli board export, by name first, then by KiCad's default colours. */
function boardLayer(m: THREE.MeshStandardMaterial): BoardLayer {
  const n = (m.name || "").toLowerCase();
  const c = m.color;
  if (/mask/.test(n)) return "mask";
  if (/silk|legend/.test(n)) return "silk";
  if (/pad|finish|enig|hasl|plating|gold/.test(n)) return "pad";
  if (/copper|track|_cu|cu_/.test(n)) return "copper";
  if (/body|fr4|substrate|core|board|edge/.test(n)) return "body";
  const near = (r: number, g: number, b: number, e: number) => Math.abs(c.r - r) < e && Math.abs(c.g - g) < e && Math.abs(c.b - b) < e;
  const tan = c.r > 0.25 && c.g > 0.25 && c.b < c.g * 0.85 && Math.abs(c.r - c.g) < 0.12;
  const white = c.r > 0.82 && c.g > 0.82 && c.b > 0.82;
  if ((m.transparent || m.opacity < 1) && !tan && !white) return "mask";
  if (near(0.7, 0.61, 0, 0.08) || (c.r > 0.6 && c.g > 0.45 && c.b < 0.15)) return "pad";
  // KiCad's copper grey: exposed pads, and tracks seen through the mask.
  if (near(0.5, 0.5, 0.5, 0.03)) return "pad";
  return white ? "silk" : "body";
}

/**
 * Board layers drawn like KiCad's own render (the Etch board viewer recipe).
 * kicad-cli writes board colours as sRGB values in glTF's linear colour
 * factor, so they are read back as sRGB or a dark green mask comes out pale.
 * Mask is a thin clearcoat over the copper; pads are an ENIG finish; silk and
 * mask get polygon offsets so the coplanar layers never z-fight.
 */
function boardMaterial(src: THREE.MeshStandardMaterial): THREE.MeshStandardMaterial {
  const layer = boardLayer(src);
  const color = src.color.clone().convertSRGBToLinear();
  let m: THREE.MeshStandardMaterial;
  if (layer === "mask") {
    m = new THREE.MeshPhysicalMaterial({
      color,
      transparent: true,
      // KiCad exports mask at alpha .83; a palette pass drops it to 1. Either way, copper shows through faintly.
      opacity: src.opacity < 1 ? Math.max(0.9, src.opacity) : 0.92,
      roughness: 0.45,
      metalness: 0,
      // Bara's studio environment is brighter than KiCad's: a lighter coat keeps the mask green at grazing angles.
      clearcoat: 0.18,
      clearcoatRoughness: 0.35,
      specularIntensity: 0.5,
      envMapIntensity: 0.4,
      depthWrite: false,
      polygonOffset: true,
      polygonOffsetFactor: -1,
      polygonOffsetUnits: -2,
    });
  } else if (layer === "silk") {
    m = new THREE.MeshStandardMaterial({ color, roughness: 0.85, metalness: 0, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -4 });
  } else if (layer === "pad") {
    m = new THREE.MeshStandardMaterial({ color: 0xdfb85e, metalness: 1, roughness: 0.24 });
  } else if (layer === "copper") {
    m = new THREE.MeshStandardMaterial({ color, metalness: 0.5, roughness: 0.5 });
  } else {
    m = new THREE.MeshStandardMaterial({ color, roughness: 0.8, metalness: 0 });
  }
  m.name = src.name;
  m.userData.boardLayer = layer;
  return m;
}

/**
 * Component bodies from STEP models (colours already linear). Light,
 * unsaturated colours are pins and shields, so they read as metal; palette
 * textures (gltf-transform palette) sample nearest so colours never bleed
 * across palette cells. Nearly opaque layers become opaque: translucent
 * meshes sort badly and look washed out.
 */
function partMaterial(src: THREE.Material): THREE.MeshStandardMaterial {
  const m: THREE.MeshStandardMaterial = (src as THREE.MeshStandardMaterial).isMeshStandardMaterial
    ? (src as THREE.MeshStandardMaterial).clone()
    : new THREE.MeshStandardMaterial({ color: (src as THREE.MeshBasicMaterial).color ?? new THREE.Color("#8a8f94"), roughness: 0.55 });
  if (m.map) {
    m.map.magFilter = THREE.NearestFilter;
    m.map.minFilter = THREE.NearestFilter;
    m.map.generateMipmaps = false;
    m.map.needsUpdate = true;
  } else {
    const c = m.color;
    const max = Math.max(c.r, c.g, c.b);
    const min = Math.min(c.r, c.g, c.b);
    const metal = m.metalness > 0.5 || (max > 0.35 && max - min < 0.12);
    m.metalness = metal ? 0.6 : Math.min(m.metalness, 0.05);
    m.roughness = metal ? 0.36 : 0.48;
  }
  if (m.transparent && m.opacity >= 0.75) {
    m.transparent = false;
    m.opacity = 1;
    m.depthWrite = true;
  }
  if (m.transparent) m.depthWrite = false;
  m.side = THREE.FrontSide;
  return m;
}

const texels = new WeakMap<THREE.Texture, ImageData | null>();
function texelData(tex: THREE.Texture): ImageData | null {
  if (texels.has(tex)) return texels.get(tex) ?? null;
  let data: ImageData | null = null;
  const img = tex.image as CanvasImageSource & { width: number; height: number };
  try {
    const cv = document.createElement("canvas");
    cv.width = img.width;
    cv.height = img.height;
    const ctx = cv.getContext("2d", { willReadFrequently: true });
    if (ctx) {
      ctx.drawImage(img, 0, 0);
      data = ctx.getImageData(0, 0, cv.width, cv.height);
    }
  } catch {
    data = null;
  }
  texels.set(tex, data);
  return data;
}

/**
 * The one colour a palette-textured geometry samples (gltf-transform palette
 * bakes flat colours into a texture), or null when it samples several.
 */
function flatPaletteColor(tex: THREE.Texture, g: THREE.BufferGeometry): THREE.Color | null {
  const uv = g.attributes.uv as THREE.BufferAttribute | undefined;
  const data = uv ? texelData(tex) : null;
  if (!uv || !data) return null;
  const step = Math.max(1, Math.floor(uv.count / 4000));
  let first = -1;
  for (let i = 0; i < uv.count; i += step) {
    // glTF textures are not flipped: v runs down the image.
    const x = Math.min(data.width - 1, Math.max(0, Math.floor(uv.getX(i) * data.width)));
    const y = Math.min(data.height - 1, Math.max(0, Math.floor(uv.getY(i) * data.height)));
    const o = (y * data.width + x) * 4;
    const rgb = (data.data[o] << 16) | (data.data[o + 1] << 8) | data.data[o + 2];
    if (first < 0) first = rgb;
    else if (rgb !== first) return null;
  }
  return first < 0 ? null : new THREE.Color().setHex(first, THREE.SRGBColorSpace);
}

function studioMaterial(src: THREE.Material, board: boolean, g: THREE.BufferGeometry): THREE.MeshStandardMaterial {
  let std = src as THREE.MeshStandardMaterial;
  if (board && std.isMeshStandardMaterial && std.map) {
    // A palette material holding one board layer (mask, silk, FR4): back to a flat colour and drawn as that layer.
    const c = flatPaletteColor(std.map, g);
    if (c) {
      std = std.clone();
      std.map = null;
      std.color.copy(c);
      return boardMaterial(std);
    }
  }
  // A board GLB's component bodies come from STEP models and are drawn as parts.
  if (board && std.isMeshStandardMaterial && !std.map && boardLayer(std) !== "body") return boardMaterial(std);
  if (board && std.isMeshStandardMaterial && !std.map && /fr4|substrate|core|board/i.test(std.name)) return boardMaterial(std);
  return partMaterial(std);
}

/**
 * Meshopt GLBs are quantised (KHR_mesh_quantization): positions and normals are
 * normalised integers with the scale on the node. Baking the node matrix into
 * an integer attribute clamps it to [-1, 1], so attributes become float first.
 */
function floatAttributes(g: THREE.BufferGeometry): void {
  for (const name of Object.keys(g.attributes)) {
    // Interleaved buffers (meshopt's default vertex layout) are copied out too: mergeGeometries needs plain ones.
    const a = g.attributes[name] as THREE.BufferAttribute | THREE.InterleavedBufferAttribute;
    if (!("isInterleavedBufferAttribute" in a && a.isInterleavedBufferAttribute) && a.array instanceof Float32Array && !a.normalized) continue;
    const out = new Float32Array(a.count * a.itemSize);
    for (let i = 0; i < a.count; i++) for (let k = 0; k < a.itemSize; k++) out[i * a.itemSize + k] = a.getComponent(i, k);
    g.setAttribute(name, new THREE.BufferAttribute(out, a.itemSize, false));
  }
}

/** mergeGeometries needs all indexed or none: keep indices (a third of the vertices) unless the list is mixed. */
function sameIndexing(list: THREE.BufferGeometry[]): THREE.BufferGeometry[] {
  if (list.every((g) => g.index) || list.every((g) => !g.index)) return list;
  return list.map((g) => (g.index ? g.toNonIndexed() : g));
}

function convert(scene: THREE.Object3D, board: boolean): LoadedModel {
  const root = new THREE.Group();
  scene.scale.setScalar(1000);
  scene.rotation.set(Math.PI / 2, 0, 0);
  root.add(scene);
  root.updateMatrixWorld(true);
  const byMat = new Map<THREE.Material, THREE.BufferGeometry[]>();
  const all: THREE.BufferGeometry[] = [];
  const fpBoxes = new Map<string, THREE.Box3>();
  root.traverse((o) => {
    const mesh = o as THREE.Mesh;
    if (!mesh.isMesh) return;
    const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
    const src = mesh.geometry;
    const parts: { g: THREE.BufferGeometry; mat: THREE.Material }[] = [];
    if (Array.isArray(mesh.material) && src.groups.length) {
      // Groups index into the index buffer; after toNonIndexed vertex i is index slot i.
      const flat = src.index ? src.toNonIndexed() : src;
      for (const gr of src.groups) {
        const g = new THREE.BufferGeometry();
        for (const name of Object.keys(flat.attributes)) {
          const a = flat.attributes[name] as THREE.BufferAttribute;
          const arr = (a.array as Float32Array).slice(gr.start * a.itemSize, (gr.start + gr.count) * a.itemSize);
          g.setAttribute(name, new THREE.BufferAttribute(arr, a.itemSize, a.normalized));
        }
        parts.push({ g, mat: mats[gr.materialIndex ?? 0] ?? mats[0] });
      }
    } else {
      parts.push({ g: src.clone(), mat: mats[0] });
    }
    for (const { g, mat } of parts) {
      floatAttributes(g);
      g.applyMatrix4(mesh.matrixWorld);
      const keepUv = !!(mat as THREE.MeshStandardMaterial).map && !!g.attributes.uv;
      for (const name of Object.keys(g.attributes)) if (name !== "position" && name !== "normal" && !(keepUv && name === "uv")) g.deleteAttribute(name);
      if (!g.attributes.normal) g.computeVertexNormals();
      const list = byMat.get(mat) ?? [];
      list.push(g);
      byMat.set(mat, list);
      const plain = g.clone();
      if (plain.attributes.uv) plain.deleteAttribute("uv");
      all.push(plain);
      const ref = board ? footprintOf(mesh) : null;
      if (ref) {
        plain.computeBoundingBox();
        const b = fpBoxes.get(ref) ?? new THREE.Box3();
        if (plain.boundingBox) b.union(plain.boundingBox);
        fpBoxes.set(ref, b);
      }
    }
  });
  const groups: MeshGroup[] = [];
  for (const [mat, list] of byMat) {
    // Mixed uv presence inside one material: drop uv so the merge succeeds.
    if (list.some((g) => !g.attributes.uv)) for (const g of list) if (g.attributes.uv) g.deleteAttribute("uv");
    const geometry = list.length === 1 ? list[0] : mergeGeometries(sameIndexing(list), false);
    if (!geometry) continue;
    const material = studioMaterial(mat, board, geometry);
    if (!material.map && geometry.attributes.uv) geometry.deleteAttribute("uv");
    groups.push({ geometry, material, weight: geometry.attributes.position.count });
  }
  // Opaque first, translucent last, so translucent layers sort over the rest.
  groups.sort((a, b) => Number(a.material.transparent) - Number(b.material.transparent));
  const merged = all.length ? mergeGeometries(sameIndexing(all), false) : null;
  const bbox = new THREE.Box3();
  if (merged) {
    merged.computeBoundingBox();
    if (merged.boundingBox) bbox.copy(merged.boundingBox);
  }
  const footprints = [...fpBoxes].map(([ref, box]) => ({ ref, box }));
  return { root, groups, merged, bbox, footprints };
}

/** `board`: a kicad-cli board export, whose layers get the KiCad board look. */
export function loadModel(url: string, board = false): Promise<LoadedModel | null> {
  const key = `${board ? "b" : "p"}:${url}`;
  let p = cache.get(key);
  if (!p) {
    p = loader
      .loadAsync(url)
      .then((gltf) => convert(gltf.scene, board))
      .catch(() => null);
    cache.set(key, p);
  }
  return p;
}

/** Warm the cache for scene.ready's preload list (GLBs only). */
export function preloadModels(urls: string[] | undefined): void {
  for (const u of urls ?? []) if (/\.glb(\?|$)/i.test(u)) void loadModel(u);
}

/** Pick the model asset for a part (lod1 first for arrays). */
export function modelAsset(assets: AssetRef[] | undefined, preferLod: boolean): AssetRef | null {
  const usable = (assets ?? []).filter((a) => a.kind === "glb" && a.status !== "missing" && a.status !== "pending" && a.url);
  if (preferLod) {
    const lod = usable.find((a) => a.role === "model_lod1");
    if (lod) return lod;
  }
  return usable.find((a) => a.role === "model" || !a.role) ?? usable[0] ?? null;
}

export type ModelState = { status: "none" } | { status: "loading" } | { status: "ready"; model: LoadedModel } | { status: "failed" };

/** Bumped whenever a model finishes loading, so shadows and framing can refresh. */
let loadedVersion = 0;
const listeners = new Set<() => void>();
export function onModelsChanged(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}
export function modelsVersion(): number {
  return loadedVersion;
}

export function useModel(url: string | null, board = false): ModelState {
  const [state, setState] = useState<ModelState>(url ? { status: "loading" } : { status: "none" });
  useEffect(() => {
    if (!url) {
      setState({ status: "none" });
      return;
    }
    let live = true;
    setState({ status: "loading" });
    void loadModel(url, board).then((m) => {
      if (!live) return;
      setState(m ? { status: "ready", model: m } : { status: "failed" });
      loadedVersion++;
      for (const l of listeners) l();
    });
    return () => {
      live = false;
    };
  }, [url, board]);
  return state;
}
