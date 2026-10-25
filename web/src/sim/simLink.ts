// What the 3D viewport needs from the running simulation to put click targets on the model: the
// slots (knobs, sticks, dials, switches), the action that reaches the engine, and the live state.
// The play surface sets it while it is open; the viewport's SimHotspotsHost reads it.
import { create } from "zustand";
import type { Slot } from "./SimHotspots";
import type { InputAction } from "./remote";

export interface SimLink {
  slots: Slot[];
  act: ((id: string, action: InputAction, value?: number | boolean) => void) | null;
  closed: Record<string, boolean>;
  powered: boolean;
}

export const useSimLink = create<SimLink>(() => ({ slots: [], act: null, closed: {}, powered: false }));
