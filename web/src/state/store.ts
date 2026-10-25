// App state (zustand). Build follows SPEC 9 exactly; everything else is view state.
import { create } from "zustand";
import type { Build, Health, ServerPayloads, Vocab } from "../spec/types";
import type { ConnStatus } from "../net/connection";
import type { Mode } from "../net/mode";
import type { EngineState } from "../net/engine";
import { emptyView, type ViewState } from "./view";

export interface LogEntry {
  id: number;
  t: number;
  dir: "in" | "out" | "drop";
  type: string;
  seq?: number;
  /** Build the event belongs to: with canvas tabs, not always the one on screen. */
  buildId?: string;
  msgId?: string;
  note?: string;
  unknown?: boolean;
  raw: string;
}

export type Overlay = "inspector" | "swap" | "resize" | "connect" | "addpart" | "focus" | null;
/** Right panel tabs, as in the Figma layout: Design (what), Build (how it was decided), Code (wiring, board, firmware). */
export type RightTab = "design" | "build" | "code";
export type CodeTab = "connections" | "board" | "firmware";
export type ViewPreset = "iso" | "top" | "bottom" | "front" | "side" | "scene";

export interface Toggles {
  case: boolean;
  board: boolean;
  keycaps: boolean;
  labels: boolean;
}

export interface PendingStart {
  msgId: string;
  prompt: string;
  ts: string;
  at: number;
}

/** One canvas tab in the workspace. `name` is null until renamed: the tab then shows the build's prompt. */
export interface CanvasMeta {
  id: string;
  name: string | null;
}

/** What each canvas keeps for itself; the active canvas's copy lives in the top-level fields (state/canvases.ts). */
export type CanvasSnapshot = Pick<
  AppState,
  | "build"
  | "view"
  | "pendingStart"
  | "clarifySending"
  | "clarifyError"
  | "selection"
  | "inspectPartId"
  | "moving"
  | "focusKey"
  | "openedFromLibrary"
  | "hoverConnection"
  | "explode"
  | "preset"
  | "toggles"
  | "rightTab"
  | "codeTab"
  | "overlay"
  | "colorTarget"
  | "resizeTarget"
  | "dismissedWarnings"
  | "dragPose"
  | "companions"
>;

export interface AppState {
  mode: Mode;
  /** How the deployed site reached the engine (net/engine.ts); "local" when no lookup ran. */
  engine: EngineState;
  engineDetail: string | null;
  conn: ConnStatus;
  hello: ServerPayloads["hello"] | null;
  screen: "home" | "drafts" | "workspace";
  build: Build | null;
  view: ViewState;
  pendingStart: PendingStart | null;
  clarifySending: string | null;
  clarifyError: string | null;
  log: LogEntry[];
  logOpen: boolean;
  selection: string | null;
  /** Catalog part shown in the inspector when it has no instance (C06 candidate click). */
  inspectPartId: string | null;
  /** Instance with the MoveGizmo attached (C20). */
  moving: string | null;
  /** Part pulled out of the build into focus: its label key (one per catalog part, the case, the board). */
  focusKey: string | null;
  /** Build id when the open build came from the library (not started in this page). */
  openedFromLibrary: string | null;
  hoverConnection: string | null;
  explode: number;
  preset: ViewPreset;
  cameraNonce: number;
  toggles: Toggles;
  rightTab: RightTab;
  codeTab: CodeTab;
  overlay: Overlay;
  colorTarget: { instance_id?: string; enclosure_id?: string } | null;
  resizeTarget: { enclosure_id?: string; board_id?: string } | null;
  vocab: Vocab | null;
  health: Health | null;
  dismissedWarnings: string[];
  toast: string | null;
  /** Local pose shown while a move is committing (C20). */
  dragPose: { instance_id: string; position_mm: number[]; rotation_deg: number[] } | null;
  /** Other canvases whose devices stand beside this one ("add a mouse to the keyboard"). */
  companions: string[];
  /** Canvas tabs in order; there is always at least one. */
  canvases: CanvasMeta[];
  activeCanvas: string;
  /** Saved state of every canvas but the active one, by canvas id. Background builds keep folding in here. */
  canvasStash: Record<string, CanvasSnapshot>;
  /** Canvas ids whose build is being fetched again after a reload. */
  canvasRestoring: string[];
  /** Part the on-stage agent is working on; the viewport outlines it (bot/agent.ts). */
  agentFocus: string | null;
  /** The bot has left the prompt bar and is working on the canvas. */
  agentOut: boolean;
  /** Part under the pointer in the viewport (the bot explains it). */
  hoverPart: string | null;
  /** Exploded-view label under the pointer: its part is outlined (three/labels.tsx). */
  hoverLabel: string | null;
  /** A finished build is being re-performed (bot/replay.ts). */
  replaying: boolean;
}

let logId = 0;
const LOG_CAP = 600;

export const useApp = create<AppState>(() => ({
  mode: { mock: false, speed: 1, fixture: null, server: null },
  engine: "local",
  engineDetail: null,
  conn: "connecting",
  hello: null,
  screen: "home",
  build: null,
  view: emptyView(),
  pendingStart: null,
  clarifySending: null,
  clarifyError: null,
  log: [],
  logOpen: false,
  selection: null,
  inspectPartId: null,
  moving: null,
  focusKey: null,
  openedFromLibrary: null,
  hoverConnection: null,
  explode: 0,
  preset: "scene",
  cameraNonce: 0,
  toggles: { case: true, board: true, keycaps: true, labels: false },
  rightTab: "design",
  codeTab: "board",
  overlay: null,
  colorTarget: null,
  resizeTarget: null,
  vocab: null,
  health: null,
  dismissedWarnings: [],
  toast: null,
  dragPose: null,
  companions: [],
  canvases: [{ id: "c1", name: null }],
  activeCanvas: "c1",
  canvasStash: {},
  canvasRestoring: [],
  agentFocus: null,
  agentOut: false,
  hoverPart: null,
  hoverLabel: null,
  replaying: false,
}));

export function pushLog(entry: Omit<LogEntry, "id" | "t">): void {
  useApp.setState((s) => {
    const next = s.log.length >= LOG_CAP ? s.log.slice(s.log.length - LOG_CAP + 1) : s.log.slice();
    next.push({ ...entry, id: ++logId, t: Date.now() });
    return { log: next };
  });
}

export function select(instanceId: string | null): void {
  useApp.setState((s) => ({
    selection: instanceId,
    inspectPartId: null,
    overlay: instanceId ? (s.overlay === "swap" && s.selection === instanceId ? "swap" : "inspector") : null,
  }));
}

/** Pulls one part out into focus (null puts it back); the right column shows the agent card. */
export function focusPart(key: string | null): void {
  const st = useApp.getState().build?.status;
  if (key && (st === "running" || st === "awaiting_input")) {
    // parts are still moving into place; pulling one out now left a half-applied layout
    showToast("Parts can be pulled out once the build is done.");
    return;
  }
  useApp.setState((s) =>
    key
      ? { focusKey: key, overlay: "focus" }
      : // putting it back leaves nothing selected: no outline or name tag lingers on the whole build
        { focusKey: null, overlay: s.overlay === "focus" ? null : s.overlay, selection: s.focusKey ? null : s.selection, moving: null },
  );
}

export function setView(preset: ViewPreset): void {
  // a new view is a new look at the whole build: put a focused part back first
  if (useApp.getState().focusKey) focusPart(null);
  useApp.setState((s) => ({ preset, cameraNonce: s.cameraNonce + 1 }));
}

export function showToast(text: string): void {
  useApp.setState({ toast: text });
  setTimeout(() => {
    if (useApp.getState().toast === text) useApp.setState({ toast: null });
  }, 4000);
}
