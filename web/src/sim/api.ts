// Programmatic handle on the running simulation, for anything that wants to demo the device
// (the on-screen bot): list the keys with where they sit on screen, press and release them, and
// follow what the device outputs. Everything is a no-op while simulation mode is closed.
import type { SimMachine, SimSnapshot } from "./machine";
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

let active: SimMachine | null = null;
const listeners = new Set<(snap: SimSnapshot | null) => void>();
let unsubscribe: (() => void) | null = null;

/** SimView registers its machine here while it runs (null when it goes away). */
export function setActiveMachine(m: SimMachine | null): void {
  unsubscribe?.();
  unsubscribe = null;
  active = m;
  if (m) unsubscribe = m.subscribe(() => emit(m.snapshot()));
  emit(m ? m.snapshot() : null);
}

function emit(snap: SimSnapshot | null): void {
  for (const fn of listeners) fn(snap);
}

export function simIsOpen(): boolean {
  return useSimPanel.getState().open && active !== null;
}

export { openSimPanel as simOpen, closeSimPanel as simClose };

export function simKeys(): SimKeyInfo[] {
  const m = active;
  if (!m) return [];
  const names = m.device.layers.map((l) => l.name);
  return m.device.keys.map((k) => {
    const el = typeof document !== "undefined" ? document.querySelector(`[data-sim-key="${CSS.escape(k.id)}"]`) : null;
    return { id: k.id, label: legend(m.bindingFor(k.pos), names), side: k.side, pos: k.pos, rect: el ? el.getBoundingClientRect() : null };
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
export function simSnapshot(): SimSnapshot | null {
  return active?.snapshot() ?? null;
}

/** Called on every visible change (key output, display, layer, console); null when the sim closes. */
export function simSubscribe(fn: (snap: SimSnapshot | null) => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}
