// Canvas tabs: several builds open in one workspace. The active canvas lives in the store's
// top-level fields, so every component reads it as before; the others wait in canvasStash and
// keep folding their own build's events while they are in the background.
import type { ServerEnvelope, ServerPayloads } from "../spec/types";
import { createBuild, reduceBuild } from "./reducer";
import { emptyView, reduceView } from "./view";
import { useApp, type AppState, type CanvasMeta, type CanvasSnapshot, type PendingStart } from "./store";

export const CANVAS_KEYS = [
  "build",
  "view",
  "pendingStart",
  "clarifySending",
  "clarifyError",
  "selection",
  "inspectPartId",
  "moving",
  "focusKey",
  "openedFromLibrary",
  "hoverConnection",
  "explode",
  "preset",
  "toggles",
  "rightTab",
  "codeTab",
  "overlay",
  "colorTarget",
  "resizeTarget",
  "dismissedWarnings",
  "dragPose",
  "companions",
] as const satisfies readonly (keyof CanvasSnapshot)[];

/** A canvas with nothing on it, looked at the way a fresh page looks. */
export function blankCanvas(): CanvasSnapshot {
  return {
    build: null,
    view: emptyView(),
    pendingStart: null,
    clarifySending: null,
    clarifyError: null,
    selection: null,
    inspectPartId: null,
    moving: null,
    focusKey: null,
    openedFromLibrary: null,
    hoverConnection: null,
    explode: 0,
    preset: "scene",
    toggles: { case: true, board: true, keycaps: true, labels: false },
    rightTab: "design",
    codeTab: "board",
    overlay: null,
    colorTarget: null,
    resizeTarget: null,
    dismissedWarnings: [],
    dragPose: null,
    companions: [],
  };
}

export function snapshotOf(s: AppState): CanvasSnapshot {
  const out = {} as Record<string, unknown>;
  for (const k of CANVAS_KEYS) out[k] = s[k];
  return out as CanvasSnapshot;
}

/** The state of any canvas, active or not. */
export function canvasState(s: AppState, id: string): CanvasSnapshot | null {
  if (id === s.activeCanvas) return snapshotOf(s);
  return s.canvasStash[id] ?? null;
}

/** Patch one canvas: the top-level fields when it is active, its stash entry otherwise. */
export function patchCanvas(id: string, patch: Partial<CanvasSnapshot> | ((c: CanvasSnapshot) => Partial<CanvasSnapshot>)): void {
  useApp.setState((s) => {
    const cur = canvasState(s, id);
    if (!cur) return {};
    const p = typeof patch === "function" ? patch(cur) : patch;
    if (id === s.activeCanvas) return p;
    return { canvasStash: { ...s.canvasStash, [id]: { ...cur, ...p } } };
  });
}

/** Which canvas shows this build. */
export function canvasOfBuild(s: AppState, buildId: string | null | undefined): string | null {
  if (!buildId) return null;
  if (s.build?.build_id === buildId) return s.activeCanvas;
  for (const [id, c] of Object.entries(s.canvasStash)) if (c.build?.build_id === buildId) return id;
  return null;
}

/** Which canvas sent this build.start. */
export function canvasOfStart(s: AppState, msgId: string): string | null {
  if (s.pendingStart?.msgId === msgId) return s.activeCanvas;
  for (const [id, c] of Object.entries(s.canvasStash)) if (c.pendingStart?.msgId === msgId) return id;
  return null;
}

/** The canvas once the engine accepted its build.start: a fresh build, looked at from the start. */
export function startedCanvas(pending: PendingStart, buildId: string): Partial<CanvasSnapshot> {
  return {
    build: createBuild(buildId, pending.prompt, pending.ts),
    view: emptyView(pending.at),
    pendingStart: null,
    selection: null,
    overlay: null,
    focusKey: null,
    dismissedWarnings: [],
    explode: 0,
    dragPose: null,
  };
}

/** Folds one build-scoped event into the canvas showing that build. */
export function foldBuildEvent(c: CanvasSnapshot, env: ServerEnvelope, now: number): Partial<CanvasSnapshot> {
  if (env.type === "build.snapshot") {
    const b = (env.payload as ServerPayloads["build.snapshot"]).build;
    return { build: b, view: reduceView(c.build ? c.view : emptyView(), env, now) };
  }
  if (!c.build) return {};
  const patch: Partial<CanvasSnapshot> = { build: reduceBuild(c.build, env), view: reduceView(c.view, env, now) };
  if ((env.type === "placement.updated" || env.type === "edit.rejected") && c.dragPose) patch.dragPose = null;
  if (env.type === "part.removed" && c.selection === (env.payload as { instance_id?: string }).instance_id) {
    patch.selection = null;
    patch.overlay = null;
  }
  if (env.type === "build.failed" || env.type === "clarify.resolved") patch.clarifySending = null;
  return patch;
}

function nextId(canvases: CanvasMeta[]): string {
  const n = canvases.reduce((m, c) => Math.max(m, Number(c.id.slice(1)) || 0), 0);
  return `c${n + 1}`;
}

/** Swap the top-level fields for another canvas's; the camera goes to that canvas's view. */
function activate(s: AppState, id: string, stash: Record<string, CanvasSnapshot>): Partial<AppState> {
  const { [id]: next, ...rest } = stash;
  return { ...(next ?? blankCanvas()), canvasStash: rest, activeCanvas: id, cameraNonce: s.cameraNonce + 1, agentFocus: null, hoverPart: null };
}

export function switchCanvas(id: string): void {
  useApp.setState((s) => {
    if (id === s.activeCanvas || !s.canvasStash[id]) return {};
    return activate(s, id, { ...s.canvasStash, [s.activeCanvas]: snapshotOf(s) });
  });
}

/** What a new canvas starts out as besides its id: a name, the device kind, what it pairs with. */
export type NewCanvas = Partial<Omit<CanvasMeta, "id">>;

/** A new empty canvas after the active one, switched to. Returns its id. */
export function addCanvas(meta: NewCanvas = {}): string {
  const s = useApp.getState();
  const id = nextId(s.canvases);
  const at = s.canvases.findIndex((c) => c.id === s.activeCanvas) + 1;
  const canvases = [...s.canvases.slice(0, at), { name: null, ...meta, id }, ...s.canvases.slice(at)];
  useApp.setState({
    canvases,
    ...activate(s, id, { ...s.canvasStash, [s.activeCanvas]: snapshotOf(s), [id]: blankCanvas() }),
    screen: "workspace",
  });
  return id;
}

/**
 * A second device next to the one on screen: a new canvas, switched to, linked both ways with
 * every canvas already in this one's scene. Returns its id.
 */
export function addCompanionCanvas(meta: NewCanvas = {}): string {
  const from = useApp.getState().activeCanvas;
  const scene = [from, ...useApp.getState().companions];
  const id = addCanvas(meta);
  useApp.setState((s) => {
    const stash = { ...s.canvasStash };
    for (const c of scene) if (stash[c]) stash[c] = { ...stash[c], companions: [...stash[c].companions.filter((x) => x !== id), id] };
    return { companions: scene, canvasStash: stash };
  });
  return id;
}

export function renameCanvas(id: string, name: string): void {
  const n = name.trim();
  useApp.setState((s) => ({ canvases: s.canvases.map((c) => (c.id === id ? { ...c, name: n || null } : c)) }));
}

/** Removes a canvas; closing the last one leaves a fresh empty canvas. Returns what it held. */
export function closeCanvas(id: string): CanvasSnapshot | null {
  if (useApp.getState().canvases.every((c) => c.id !== id)) return null;
  const closed = canvasState(useApp.getState(), id);
  // the closed device leaves every scene it stood in
  for (const c of useApp.getState().canvases)
    if (c.id !== id) patchCanvas(c.id, (cs) => (cs.companions.includes(id) ? { companions: cs.companions.filter((x) => x !== id) } : {}));
  const s = useApp.getState();
  const at = s.canvases.findIndex((c) => c.id === id);
  const left = s.canvases.filter((c) => c.id !== id);
  if (left.length === 0) {
    const fresh = nextId(s.canvases);
    useApp.setState({ ...blankCanvas(), canvases: [{ id: fresh, name: null }], activeCanvas: fresh, canvasStash: {}, screen: "home" });
    return closed;
  }
  if (id !== s.activeCanvas) {
    const { [id]: _gone, ...rest } = s.canvasStash;
    useApp.setState({ canvases: left, canvasStash: rest });
    return closed;
  }
  // the neighbour to the right takes its place, or the one to the left at the end of the strip
  const next = left[Math.min(at, left.length - 1)].id;
  useApp.setState({ canvases: left, ...activate(s, next, s.canvasStash) });
  return closed;
}

/** Opens a build on a canvas of its own: the one already showing it, the active one when empty, else a new one. */
export function canvasForOpening(buildId: string): string {
  const s = useApp.getState();
  const showing = canvasOfBuild(s, buildId);
  if (showing) {
    switchCanvas(showing);
    return showing;
  }
  if (!s.build && !s.pendingStart) return s.activeCanvas;
  return addCanvas();
}

export type CanvasStatus = "empty" | "starting" | "restoring" | "running" | "awaiting_input" | "done" | "failed" | "cancelled";

export function canvasStatus(s: AppState, id: string): CanvasStatus {
  if (s.canvasRestoring.includes(id)) return "restoring";
  const c = canvasState(s, id);
  if (!c) return "empty";
  if (c.pendingStart) return "starting";
  if (!c.build) return "empty";
  const st = String(c.build.status);
  return (["running", "awaiting_input", "done", "failed", "cancelled"] as const).find((k) => k === st) ?? "running";
}

export function canvasLabel(meta: CanvasMeta, c: CanvasSnapshot | null): string {
  return meta.name ?? c?.pendingStart?.prompt ?? c?.build?.prompt ?? "New canvas";
}

// ---- kept across reloads ----

export const CANVAS_STORE = "bara.canvases";

export interface StoredCanvas {
  id: string;
  name: string | null;
  build_id: string | null;
  prompt: string | null;
  companions?: string[];
  kind?: string | null;
  pairs_with?: string | null;
}

export interface StoredCanvases {
  active: string;
  canvases: StoredCanvas[];
}

export function serializeCanvases(s: AppState): StoredCanvases {
  return {
    active: s.activeCanvas,
    canvases: s.canvases.map((m) => {
      const c = canvasState(s, m.id);
      return {
        id: m.id,
        name: m.name,
        build_id: c?.build?.build_id ?? null,
        prompt: c?.build?.prompt ?? null,
        companions: c?.companions ?? [],
        kind: m.kind ?? null,
        pairs_with: m.pairsWith ?? null,
      };
    }),
  };
}

/** The stored list, or null when there is none or it is not ours. */
export function parseCanvases(raw: string | null): StoredCanvases | null {
  if (!raw) return null;
  try {
    const v = JSON.parse(raw) as Partial<StoredCanvases>;
    if (!Array.isArray(v.canvases)) return null;
    const canvases = v.canvases
      .filter((c): c is StoredCanvas => !!c && typeof c.id === "string" && /^c\d+$/.test(c.id))
      .map((c) => ({
        id: c.id,
        name: typeof c.name === "string" ? c.name : null,
        build_id: typeof c.build_id === "string" ? c.build_id : null,
        prompt: typeof c.prompt === "string" ? c.prompt : null,
        companions: Array.isArray(c.companions) ? c.companions.filter((x): x is string => typeof x === "string") : [],
        kind: typeof c.kind === "string" ? c.kind : null,
        pairs_with: typeof c.pairs_with === "string" ? c.pairs_with : null,
      }));
    if (canvases.length === 0) return null;
    const active = canvases.some((c) => c.id === v.active) ? (v.active as string) : canvases[0].id;
    return { active, canvases };
  } catch {
    return null;
  }
}

/** Puts the stored tabs back, empty; their builds are fetched afterwards (net/client.ts restoreCanvases). */
export function applyStoredCanvases(stored: StoredCanvases): void {
  const stash: Record<string, CanvasSnapshot> = {};
  const ids = new Set(stored.canvases.map((c) => c.id));
  const linked = (c: StoredCanvas) => (c.companions ?? []).filter((x) => ids.has(x) && x !== c.id);
  for (const c of stored.canvases) if (c.id !== stored.active) stash[c.id] = { ...blankCanvas(), companions: linked(c) };
  const active = stored.canvases.find((c) => c.id === stored.active);
  useApp.setState({
    ...blankCanvas(),
    companions: active ? linked(active) : [],
    canvases: stored.canvases.map((c) => ({ id: c.id, name: c.name, kind: c.kind ?? null, pairsWith: c.pairs_with && ids.has(c.pairs_with) ? c.pairs_with : null })),
    activeCanvas: stored.active,
    canvasStash: stash,
    canvasRestoring: stored.canvases.filter((c) => c.build_id).map((c) => c.id),
  });
}

/** Writes the tab list to localStorage whenever it changes; returns a stop function. */
export function startCanvasPersist(): () => void {
  let last = "";
  const write = () => {
    const s = useApp.getState();
    // nothing to keep while a reload is still fetching the builds back
    if (s.canvasRestoring.length) return;
    const next = JSON.stringify(serializeCanvases(s));
    if (next === last) return;
    last = next;
    try {
      localStorage.setItem(CANVAS_STORE, next);
    } catch {
      // storage blocked: the tabs just will not come back after a reload
    }
  };
  return useApp.subscribe(write);
}
