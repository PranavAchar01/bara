// Whether the thinking trace is open. The bots (AgentStage, PromptBar) toggle
// it, ThoughtTrace.tsx draws it and looks after Esc and outside clicks.
import { create } from "zustand";
import { useApp } from "../state/store";

export const useTrace = create<{ open: boolean }>(() => ({ open: false }));

/** Opening it with a build on the canvas shows it at the top of the Design tab, opening that panel. */
export function toggleTrace(): void {
  const open = !useTrace.getState().open;
  useTrace.setState({ open });
  if (open && useApp.getState().build) useApp.setState((s) => ({ panels: { ...s.panels, details: true }, rightTab: "design" }));
}

export function closeTrace(): void {
  useTrace.setState({ open: false });
}
