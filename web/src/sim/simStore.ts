// Simulation mode state: whether it is on, the build's input map and the running firmware, and
// what to restore when it ends. The viewport's own state (explode, toggles, focus) stays in the
// app store; entering and leaving only set and restore it.
import { create } from "zustand";
import { focusPart, useApp, type Toggles, type ViewPreset } from "../state/store";
import type { Build } from "../spec/types";
import { deriveInputMap, type InputMap, type SimInput } from "./inputMap";
import { createRuntime, press, release, type RemoteScreen, type Runtime } from "./runtime";
import { displaySpec, operatingView, type DisplaySpec, type OperatingView } from "./view";
import { openSimPanel } from "./simPanelStore";

interface Saved {
  explode: number;
  preset: ViewPreset;
  toggles: Toggles;
}

interface SimState {
  active: boolean;
  map: InputMap | null;
  runtime: Runtime | null;
  view: OperatingView;
  /** Panel of the first display part, when the build has one. */
  screen: DisplaySpec | null;
  byPressKey: Map<string, SimInput>;
  byId: Map<string, SimInput>;
  /** Input under the pointer. */
  hover: string | null;
  saved: Saved | null;
  /** Bumped when the runtime changes, so views redraw. */
  version: number;
}

export const useSim = create<SimState>(() => ({
  active: false,
  map: null,
  runtime: null,
  view: operatingView(null),
  screen: null,
  byPressKey: new Map(),
  byId: new Map(),
  hover: null,
  saved: null,
  version: 0,
}));

/** Time (ms, performance.now clock) until which an input's cap stays down, so a quick tap still shows. */
export const capHold = new Map<string, number>();
const TAP_MS = 110;

export function canSimulate(build: Build | null): boolean {
  if (!build || (build.status !== "done" && build.status !== "failed")) return false;
  return build.parts.some((p) => p.card.primary_function === "compute.mcu") || deriveInputMap(build).inputs.length > 0;
}

/** Simulation is its own screen: the engine builds the firmware and runs it (SimView). */
export function enterSimulation(): void {
  const build = useApp.getState().build;
  if (!canSimulate(build)) return;
  focusPart(null);
  openSimPanel();
}

/**
 * Where a click on the 3D device goes. The simulation screen sets these to the engine, so a press
 * runs the real firmware instead of the local typing and game stand-ins.
 */
export const simHooks: { press?: (input: SimInput) => void; release?: (input: SimInput) => void } = {};

/**
 * Put the viewport in its operating pose for the simulation screen: the case shown, nothing
 * exploded, the runtime in "pad" mode so every output comes from the engine's firmware. Returns
 * the function that restores what the workspace had.
 */
export function enterBridge(build: Build): () => void {
  const app = useApp.getState();
  const map = deriveInputMap(build);
  const display = build.parts.find((p) => map.displays.includes(p.instance_id) || p.card.primary_function?.startsWith("output.display"));
  const screen = display ? displaySpec(display) : null;
  const saved: Saved = { explode: app.explode, preset: app.preset, toggles: { ...app.toggles } };
  useApp.setState((s) => ({ explode: 0, toggles: { ...s.toggles, case: true, labels: false }, selection: null, hoverPart: null, moving: null }));
  useSim.setState({
    active: true,
    map,
    runtime: createRuntime({ ...map, mode: "pad" }, screen ? screen.w / screen.h : 4 / 3),
    view: operatingView(build),
    screen,
    byPressKey: new Map(map.inputs.map((i) => [i.pressKey, i])),
    byId: new Map(map.inputs.map((i) => [i.id, i])),
    hover: null,
    saved,
    version: 0,
  });
  return exitSimulation;
}

export function exitSimulation(): void {
  const { active, saved } = useSim.getState();
  if (!active) return;
  capHold.clear();
  simHooks.press = simHooks.release = undefined;
  useSim.setState({ active: false, runtime: null, hover: null });
  if (saved) useApp.setState({ explode: saved.explode, preset: saved.preset, toggles: saved.toggles });
}

/** Mirror what the engine says the display shows, so the screen on the 3D model draws the firmware's output. */
export function showRemote(remote: RemoteScreen): void {
  const { runtime } = useSim.getState();
  if (!runtime) return;
  runtime.remote = remote;
  useSim.setState((s) => ({ version: s.version + 1 }));
}

export function pressInput(input: SimInput): void {
  const { runtime, map } = useSim.getState();
  if (!runtime || !map) return;
  capHold.set(input.pressKey, performance.now() + TAP_MS);
  press(runtime, input, map.inputs);
  simHooks.press?.(input);
  useSim.setState((s) => ({ version: s.version + 1 }));
}

export function releaseInput(input: SimInput): void {
  const { runtime } = useSim.getState();
  if (!runtime) return;
  release(runtime, input);
  simHooks.release?.(input);
  useSim.setState((s) => ({ version: s.version + 1 }));
}

export function setHover(id: string | null): void {
  if (useSim.getState().hover !== id) useSim.setState({ hover: id });
}

export function bumpSim(): void {
  useSim.setState((s) => ({ version: s.version + 1 }));
}
