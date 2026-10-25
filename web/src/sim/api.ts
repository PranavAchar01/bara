// Programmatic handle on the running simulation, for anything that wants to demo the device
// (the on-screen bot): list the keys with where they sit on screen, press and release them, and
// follow what the device outputs. Everything is a no-op while simulation mode is closed.
import type { SimMachine } from "./machine";
import { legend } from "./machine";
import { closeSimPanel, openSimPanel, useSimPanel } from "./simPanelStore";

export interface SimKeyInfo {
  id: string;
  /** Keycap legend on the active layers ("Q", "Lower", "Space"). */
  label: string;
  side: string;
  /** Keymap position. */
  pos: number;
  /** Where the key's legend is on screen right now (CSS px), when it is drawn. */
  rect: DOMRect | null;
}

/** What the demo needs from a running device: its controls, press and release, and what it has typed. */
export interface DemoSnapshot {
  /** Everything the device has typed to its host (or printed), as plain text. */
  text: string;
}

export interface DemoMachine {
  keys(): { id: string; label: string; side: string; pos: number }[];
  press(id: string): void;
  release(id: string): void;
  /** Where a control is on screen (CSS px), for devices whose controls are drawn in 3D. */
  rectOf?(id: string): DOMRect | null;
  snapshot(): DemoSnapshot;
  subscribe(fn: () => void): () => void;
}

/** The local keyboard model seen as a demo machine. */
function fromMachine(m: SimMachine): DemoMachine {
  const names = m.device.layers.map((l) => l.name);
  return {
    keys: () => m.device.keys.map((k) => ({ id: k.id, label: legend(m.bindingFor(k.pos), names), side: k.side, pos: k.pos })),
    press: (id) => m.press(id),
    release: (id) => m.release(id),
    snapshot: () => m.snapshot(),
    subscribe: (fn) => m.subscribe(fn),
  };
}

let active: DemoMachine | null = null;
const listeners = new Set<(snap: DemoSnapshot | null) => void>();
let unsubscribe: (() => void) | null = null;

/** SimView registers its machine here while it runs (null when it goes away). */
export function setActiveMachine(machine: SimMachine | DemoMachine | null): void {
  const m = machine && "device" in machine ? fromMachine(machine) : machine;
  unsubscribe?.();
  unsubscribe = null;
  active = m;
  if (m) unsubscribe = m.subscribe(() => emit(m.snapshot()));
  emit(m ? m.snapshot() : null);
}

function emit(snap: DemoSnapshot | null): void {
  for (const fn of listeners) fn(snap);
}

export function simIsOpen(): boolean {
  return useSimPanel.getState().open && active !== null;
}

export { openSimPanel as simOpen, closeSimPanel as simClose };

export function simKeys(): SimKeyInfo[] {
  const m = active;
  if (!m) return [];
  return m.keys().map((k) => {
    const el = typeof document !== "undefined" ? document.querySelector(`[data-sim-key="${CSS.escape(k.id)}"]`) : null;
    return { ...k, rect: el ? el.getBoundingClientRect() : (m.rectOf?.(k.id) ?? null) };
  });
}

/** The first key whose legend on the active layers is `label` (case-insensitive), e.g. "Q" or "Space". */
export function simKeyFor(label: string): string | null {
  const want = label.toLowerCase();
  return simKeys().find((k) => k.label.toLowerCase() === want)?.id ?? null;
}

export function simPress(keyId: string): void {
  active?.press(keyId);
}

export function simRelease(keyId: string): void {
  active?.release(keyId);
}

/** Press, hold for `holdMs` (real time), release. */
export function simTap(keyId: string, holdMs = 90): Promise<void> {
  simPress(keyId);
  return new Promise((resolve) =>
    setTimeout(() => {
      simRelease(keyId);
      resolve();
    }, holdMs),
  );
}

/** Current state: host text, display lines by instance id, active layer, console. Null when closed. */
export function simSnapshot(): DemoSnapshot | null {
  return active?.snapshot() ?? null;
}

/** Called on every visible change (key output, display, layer, console); null when the sim closes. */
export function simSubscribe(fn: (snap: DemoSnapshot | null) => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}
