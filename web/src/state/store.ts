// App state (zustand). Build follows SPEC 9 exactly; everything else is view state.
import { create } from "zustand";
import type { Build, Health, ServerPayloads, Vocab } from "../spec/types";
import type { ConnStatus } from "../net/connection";
import type { Mode } from "../net/mode";
import { emptyView, type ViewState } from "./view";

export interface LogEntry {
  id: number;
  t: number;
  dir: "in" | "out" | "drop";
  type: string;
  seq?: number;
  msgId?: string;
  note?: string;
  unknown?: boolean;
  raw: string;
}

export type Overlay = "inspector" | "swap" | "resize" | "connect" | "addpart" | null;
export type RightTab = "parts" | "connections" | "board" | "firmware" | "checks";
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

export interface AppState {
  mode: Mode;
  conn: ConnStatus;
  hello: ServerPayloads["hello"] | null;
  screen: "home" | "workspace";
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
  hoverConnection: string | null;
  explode: number;
  preset: ViewPreset;
  cameraNonce: number;
  toggles: Toggles;
  rightTab: RightTab;
  overlay: Overlay;
  colorTarget: { instance_id?: string; enclosure_id?: string } | null;
  resizeTarget: { enclosure_id?: string; board_id?: string } | null;
  vocab: Vocab | null;
  health: Health | null;
  dismissedWarnings: string[];
  toast: string | null;
  /** Local pose shown while a move is committing (C20). */
  dragPose: { instance_id: string; position_mm: number[]; rotation_deg: number[] } | null;
}

let logId = 0;
const LOG_CAP = 600;

export const useApp = create<AppState>(() => ({
  mode: { mock: false, speed: 1, fixture: null, server: null },
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
  hoverConnection: null,
  explode: 0,
  preset: "scene",
  cameraNonce: 0,
  toggles: { case: true, board: true, keycaps: true, labels: false },
  rightTab: "parts",
  overlay: null,
  colorTarget: null,
  resizeTarget: null,
  vocab: null,
  health: null,
  dismissedWarnings: [],
  toast: null,
  dragPose: null,
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

export function setView(preset: ViewPreset): void {
  useApp.setState((s) => ({ preset, cameraNonce: s.cameraNonce + 1 }));
}

export function showToast(text: string): void {
  useApp.setState({ toast: text });
  setTimeout(() => {
    if (useApp.getState().toast === text) useApp.setState({ toast: null });
  }, 4000);
}
