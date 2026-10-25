// Devices that stand on one board are one combined device with one plain title ("Macropad with
// desktop display"). The engine keeps the scenes beside the library (GET/POST /v1/scenes, and each
// library row carries its scene); this file keeps them in the page, registers a board once all its
// devices are built, opens a whole scene from the library, and names the combined device for the
// tab, the build header and the simulator.
import { create } from "zustand";
import { getRest, openLibraryBuild } from "../net/client";
import { addCompanionCanvas, canvasOfBuild, canvasLabel, canvasState, switchCanvas } from "../state/canvases";
import { useApp, type AppState } from "../state/store";
import { linkWhenBuilt } from "./awaiting";
import type { SceneDevice } from "../sim/combined";

export interface Scene {
  scene_id: string;
  title: string;
  /** Build ids on the board, the main device first. */
  builds: string[];
}

export const useScenes = create<{ byBuild: Record<string, Scene> }>(() => ({ byBuild: {} }));

/** Remember scenes (from GET /v1/scenes, a POST answer or library rows). */
export function rememberScenes(scenes: Scene[]): void {
  if (!scenes.length) return;
  useScenes.setState((s) => {
    const byBuild = { ...s.byBuild };
    for (const sc of scenes) for (const b of sc.builds) byBuild[b] = { scene_id: sc.scene_id, title: sc.title, builds: sc.builds };
    return { byBuild };
  });
}

export async function loadScenes(): Promise<void> {
  const res = await getRest().get<{ scenes: Scene[] }>("/v1/scenes");
  if (res.ok && Array.isArray(res.body.scenes)) rememberScenes(res.body.scenes);
}

export function sceneOf(buildId: string | null | undefined): Scene | null {
  return buildId ? (useScenes.getState().byBuild[buildId] ?? null) : null;
}

/** The combined device's title for a build that stands on a board with others. */
export function useCombinedTitle(buildId: string | null | undefined): string | null {
  return useScenes((s) => (buildId ? (s.byBuild[buildId]?.title ?? null) : null));
}

/** A tab's title: the combined device's on its main device's tab; the others keep their own. */
export function useTabTitle(buildId: string | null | undefined): string | null {
  return useScenes((s) => {
    const sc = buildId ? s.byBuild[buildId] : undefined;
    return sc && sc.builds[0] === buildId ? sc.title : null;
  });
}

/** The devices on the open canvas's board, in tab order (the main device is the first one made). */
export function boardDevices(s: AppState): SceneDevice[] {
  const scene = new Set([s.activeCanvas, ...s.companions]);
  return s.canvases
    .filter((m) => scene.has(m.id))
    .map((m) => {
      const c = canvasState(s, m.id);
      return { canvasId: m.id, name: c?.build ? deviceName(c.build.build_id, canvasLabel(m, c)) : canvasLabel(m, c), build: c?.build ?? null };
    });
}

/** The engine's short device name for a stored build, when the library listing gave one. */
const deviceNames = new Map<string, string>();
export function rememberDeviceName(buildId: string, device: string | null | undefined): void {
  if (device) deviceNames.set(buildId, device);
}
function deviceName(buildId: string, fallback: string): string {
  return deviceNames.get(buildId) ?? fallback;
}

const posted = new Set<string>();

/** Once every device on the open board is built, stand them on one board in the engine and name it. */
async function register(devices: SceneDevice[]): Promise<void> {
  const builds = devices.map((d) => d.build?.build_id ?? "");
  const key = builds.join(",");
  if (posted.has(key)) return;
  posted.add(key);
  const known = sceneOf(builds[0]);
  if (known && builds.every((b) => known.builds.includes(b))) return;
  const res = await getRest().request<{ scene: Scene }>("POST", "/v1/scenes", { builds, names: devices.map((d) => d.name) });
  // an engine without scenes answers 404: asked once per board, not on every change
  if (res.ok && res.body.scene) rememberScenes([res.body.scene]);
}

/** Watches the open board; returns a stop function. */
export function startSceneSync(): () => void {
  void loadScenes().catch(() => undefined);
  return useApp.subscribe((s) => {
    if (s.mode.mock || s.companions.length === 0) return;
    const devices = boardDevices(s);
    if (devices.length < 2 || !devices.every((d) => d.build?.status === "done")) return;
    void register(devices).catch(() => undefined);
  });
}

/**
 * Opens a whole scene from the library: the main device on its canvas, every other device on a
 * canvas beside it, linked, and the main device in front. `first` is the build that was clicked.
 */
export async function openScene(scene: Scene, first: string): Promise<boolean> {
  const main = scene.builds[0] ?? first;
  if (!(await openLibraryBuild(main))) return false;
  const home = useApp.getState().activeCanvas;
  for (const b of scene.builds) {
    if (b === main) continue;
    const there = canvasOfBuild(useApp.getState(), b);
    if (there && useApp.getState().companions.includes(there)) continue;
    const id = addCompanionCanvas();
    linkWhenBuilt(id);
    await openLibraryBuild(b);
  }
  switchCanvas(home);
  useApp.setState({ screen: "workspace" });
  return true;
}
