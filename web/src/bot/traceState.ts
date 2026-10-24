// Whether the thinking trace is open. The bots (AgentStage, PromptBar) toggle
// it, ThoughtTrace.tsx draws it and looks after Esc and outside clicks.
import { create } from "zustand";

export const useTrace = create<{ open: boolean }>(() => ({ open: false }));

export function toggleTrace(): void {
  useTrace.setState((s) => ({ open: !s.open }));
}

export function closeTrace(): void {
  useTrace.setState({ open: false });
}
