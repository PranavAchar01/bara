// The shape of the build's screen as the 3D view shows it (width over height), so the firmware can
// draw its game frame to fill that screen instead of a letterboxed band.
import { create } from "zustand";

export const useScreenAspect = create<{ aspect: number | null }>(() => ({ aspect: null }));

/** Whether a frame of aspect `fb` would leave a visible band on a screen of aspect `screen`. */
export const mismatched = (fb: number, screen: number) => Math.abs(Math.log(fb / screen)) > 0.2;
