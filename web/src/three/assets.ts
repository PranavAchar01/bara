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
}

const cache = new Map<string, Promise<LoadedModel | null>>();
const loader = new GLTFLoader();
loader.setMeshoptDecoder(MeshoptDecoder);

/**
 * KiCad's GLB export marks solder mask (alpha .83) and silkscreen (alpha .9)
 * as BLEND. Drawn translucent they sort badly and look washed out; real mask
 * reads as opaque, so nearly opaque layers become opaque. Other materials pass
 * through as authored (roughness, metalness, colour from the GLB).
 */
function studioMaterial(src: THREE.Material): THREE.MeshStandardMaterial {
  const m: THREE.MeshStandardMaterial = (src as THREE.MeshStandardMaterial).isMeshStandardMaterial
    ? (src as THREE.MeshStandardMaterial).clone()
    : new THREE.MeshStandardMaterial({ color: (src as THREE.MeshBasicMaterial).color ?? new THREE.Color("#8a8f94"), roughness: 0.55 });
  if (m.transparent && m.opacity >= 0.75) {
    m.transparent = false;
    m.opacity = 1;
    m.depthWrite = true;
  }
  if (m.transparent) m.depthWrite = false;
  m.side = THREE.FrontSide;
  // Coplanar KiCad layers (mask over copper, silk over mask): pull thin skins forward.
  if (!m.map && m.roughness > 0.55 && m.metalness < 0.1 && m.color.getHSL({ h: 0, s: 0, l: 0 }).l > 0.85) {
    m.polygonOffset = true;
    m.polygonOffsetFactor = -1;
    m.polygonOffsetUnits = -1;
  }
  return m;
}

function convert(scene: THREE.Object3D): LoadedModel {
  const root = new THREE.Group();
  scene.scale.setScalar(1000);
  scene.rotation.set(Math.PI / 2, 0, 0);
  root.add(scene);
  root.updateMatrixWorld(true);
  const byMat = new Map<THREE.Material, THREE.BufferGeometry[]>();
  const all: THREE.BufferGeometry[] = [];
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
      g.applyMatrix4(mesh.matrixWorld);
      const keepUv = !!(mat as THREE.MeshStandardMaterial).map && !!g.attributes.uv;
      for (const name of Object.keys(g.attributes)) if (name !== "position" && name !== "normal" && !(keepUv && name === "uv")) g.deleteAttribute(name);
      if (!g.attributes.normal) g.computeVertexNormals();
      const flat = g.index ? g.toNonIndexed() : g;
      const list = byMat.get(mat) ?? [];
      list.push(flat);
      byMat.set(mat, list);
      const plain = flat.clone();
      if (plain.attributes.uv) plain.deleteAttribute("uv");
      all.push(plain);
    }
  });
  const groups: MeshGroup[] = [];
  for (const [mat, list] of byMat) {
    // Mixed uv presence inside one material: drop uv so the merge succeeds.
    if (list.some((g) => !g.attributes.uv)) for (const g of list) if (g.attributes.uv) g.deleteAttribute("uv");
    const geometry = list.length === 1 ? list[0] : mergeGeometries(list, false);
    if (!geometry) continue;
    groups.push({ geometry, material: studioMaterial(mat), weight: geometry.attributes.position.count });
  }
  // Opaque first, translucent last, so translucent layers sort over the rest.
  groups.sort((a, b) => Number(a.material.transparent) - Number(b.material.transparent));
  const merged = all.length ? mergeGeometries(all, false) : null;
  const bbox = new THREE.Box3();
  if (merged) {
    merged.computeBoundingBox();
    if (merged.boundingBox) bbox.copy(merged.boundingBox);
  }
  return { root, groups, merged, bbox };
}

export function loadModel(url: string): Promise<LoadedModel | null> {
  let p = cache.get(url);
  if (!p) {
    p = loader
      .loadAsync(url)
      .then((gltf) => convert(gltf.scene))
      .catch(() => null);
    cache.set(url, p);
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

export function useModel(url: string | null): ModelState {
  const [state, setState] = useState<ModelState>(url ? { status: "loading" } : { status: "none" });
  useEffect(() => {
    if (!url) {
      setState({ status: "none" });
      return;
    }
    let live = true;
    setState({ status: "loading" });
    void loadModel(url).then((m) => {
      if (!live) return;
      setState(m ? { status: "ready", model: m } : { status: "failed" });
      loadedVersion++;
      for (const l of listeners) l();
    });
    return () => {
      live = false;
    };
  }, [url]);
  return state;
}
