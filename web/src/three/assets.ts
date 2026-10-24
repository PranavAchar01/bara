// GLB loading (SPEC 3.2): one load per URL, converted once to build space
// (scale 1000, then +90 deg about X). Failures resolve to null so the caller
// draws the bbox placeholder; one bad asset never blocks the scene.
import { useEffect, useState } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { mergeGeometries } from "three/examples/jsm/utils/BufferGeometryUtils.js";
import type { AssetRef } from "../spec/types";

export interface LoadedModel {
  /** Root already converted to build space (mm, Z up). */
  root: THREE.Object3D;
  /** All meshes merged into one geometry in build space, for instancing. */
  merged: THREE.BufferGeometry | null;
  material: THREE.Material | null;
}

const cache = new Map<string, Promise<LoadedModel | null>>();
const loader = new GLTFLoader();

function convert(scene: THREE.Object3D): LoadedModel {
  const root = new THREE.Group();
  scene.scale.setScalar(1000);
  scene.rotation.set(Math.PI / 2, 0, 0);
  root.add(scene);
  root.updateMatrixWorld(true);
  const geoms: THREE.BufferGeometry[] = [];
  let material: THREE.Material | null = null;
  root.traverse((o) => {
    const mesh = o as THREE.Mesh;
    if (!mesh.isMesh) return;
    const g = mesh.geometry.clone();
    g.applyMatrix4(mesh.matrixWorld);
    // Only position and normal survive the merge so mixed attribute sets combine.
    for (const name of Object.keys(g.attributes)) if (name !== "position" && name !== "normal") g.deleteAttribute(name);
    if (!g.attributes.normal) g.computeVertexNormals();
    geoms.push(g.index ? g.toNonIndexed() : g);
    if (!material) material = Array.isArray(mesh.material) ? (mesh.material[0] ?? null) : mesh.material;
  });
  const merged = geoms.length ? mergeGeometries(geoms, false) : null;
  return { root, merged, material };
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
      if (live) setState(m ? { status: "ready", model: m } : { status: "failed" });
    });
    return () => {
      live = false;
    };
  }, [url]);
  return state;
}
