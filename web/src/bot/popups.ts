// Bara's short updates as popups: one line at a time, each gone after a moment. Anything that has
// something to say (the build stream, the agent's beats, a spoken reply) calls popup(); BotPopups draws them.
import { create } from "zustand";

export interface Popup {
  id: number;
  text: string;
}

/** How long a line stays up. */
export const POPUP_MS = 2800;
/** At most this many on screen; an older one leaves when a new one comes. */
const MAX = 2;
/** The same line again this soon is the same news (the stage and the stream both said it). */
const SAME_MS = 4000;

export const usePopups = create<{ items: Popup[] }>(() => ({ items: [] }));

let n = 0;
let last = { text: "", at: -Infinity };

export function popup(text: string, now = Date.now()): void {
  const t = text.trim();
  if (!t || (t === last.text && now - last.at < SAME_MS)) return;
  last = { text: t, at: now };
  const id = ++n;
  usePopups.setState((s) => ({ items: [...s.items, { id, text: t }].slice(-MAX) }));
  if (typeof window !== "undefined") window.setTimeout(() => dismiss(id), POPUP_MS);
}

export function dismiss(id: number): void {
  usePopups.setState((s) => ({ items: s.items.filter((p) => p.id !== id) }));
}

export function _resetPopups(): void {
  n = 0;
  last = { text: "", at: -Infinity };
  usePopups.setState({ items: [] });
}
