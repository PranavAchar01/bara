// Simulation mode state: whether it is on, the build's input map and the running firmware, and
// what to restore when it ends. The viewport's own state (explode, toggles, focus) stays in the
// app store; entering and leaving only set and restore it.
import { create } from "zustand";
import { focusPart, useApp, type Toggles, type ViewPreset } from "../state/store";
import type { Build } from "../spec/types";
import { deriveInputMap, type InputMap, type SimInput } from "./inputMap";
import { createRuntime, press, release, type Runtime } from "./runtime";
import { displaySpec, operatingView, type DisplaySpec, type OperatingView } from "./view";

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
  return !!build && build.status === "done" && deriveInputMap(build).inputs.length > 0;
}

export function enterSimulation(): void {
  const app = useApp.getState();
  const build = app.build;
  if (useSim.getState().active || !build || build.status !== "done") return;
  const map = deriveInputMap(build);
  if (!map.inputs.length) return;
  const display = build.parts.find((p) => map.displays.includes(p.instance_id));
  const screen = display ? displaySpec(display) : null;
  const saved: Saved = { explode: app.explode, preset: app.preset, toggles: { ...app.toggles } };
  focusPart(null);
  useApp.setState((s) => ({
    explode: 0,
    toggles: { ...s.toggles, case: true, labels: false },
    selection: null,
    hoverPart: null,
    moving: null,
  }));
  useSim.setState({
    active: true,
    map,
    runtime: createRuntime(map, screen ? screen.w / screen.h : 4 / 3),
    view: operatingView(build),
    screen,
    byPressKey: new Map(map.inputs.map((i) => [i.pressKey, i])),
    byId: new Map(map.inputs.map((i) => [i.id, i])),
    hover: null,
    saved,
    version: 0,
  });
}

export function exitSimulation(): void {
  const { active, saved } = useSim.getState();
  if (!active) return;
  capHold.clear();
  useSim.setState({ active: false, runtime: null, hover: null });
  if (saved) useApp.setState({ explode: saved.explode, preset: saved.preset, toggles: saved.toggles });
}

export function pressInput(input: SimInput): void {
  const { runtime, map } = useSim.getState();
  if (!runtime || !map) return;
  capHold.set(input.pressKey, performance.now() + TAP_MS);
  press(runtime, input, map.inputs);
  useSim.setState((s) => ({ version: s.version + 1 }));
}

export function releaseInput(input: SimInput): void {
  const { runtime } = useSim.getState();
  if (!runtime) return;
  release(runtime, input);
  useSim.setState((s) => ({ version: s.version + 1 }));
}

export function setHover(id: string | null): void {
  if (useSim.getState().hover !== id) useSim.setState({ hover: id });
}

export function bumpSim(): void {
  useSim.setState((s) => ({ version: s.version + 1 }));
}
