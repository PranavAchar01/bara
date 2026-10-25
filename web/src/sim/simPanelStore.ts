// The firmware simulation panel's own state, kept apart from the app store: whether it is open, and a keymap
// file the user loaded in place of the build's.
import { create } from "zustand";
import { useApp } from "../state/store";

export interface SimPanelState {
  open: boolean;
  keymap: { path: string; content: string } | null;
}

export const useSimPanel = create<SimPanelState>(() => ({ open: false, keymap: null }));

/** Opens the simulator on the whole build as laid out: nothing pulled out, exploded or mid-move. */
export function openSimPanel(): void {
  useApp.setState((s) => ({ explode: 0, focusKey: null, selection: null, overlay: null, moving: null, preset: "scene", cameraNonce: s.cameraNonce + 1 }));
  useSimPanel.setState({ open: true });
}

export function closeSimPanel(): void {
  useSimPanel.setState({ open: false });
}
