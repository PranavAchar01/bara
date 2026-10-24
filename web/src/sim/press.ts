// Cap travel for pressed inputs: how far each cap is down right now, eased toward its target.
// Mutable and frame-driven (like three/stage.ts), so a press never re-renders the scene tree.
import { capHold, useSim } from "./simStore";

/** How far a pressed key or button sinks, in mm. */
export const TRAVEL_MM = 1;

export const caps = {
  /** Current depth in mm by input press key. */
  depth: new Map<string, number>(),
  /** Bumped whenever any depth changed, so instanced meshes know to rewrite their matrices. */
  version: 0,
};

/**
 * Ease every cap toward down (held, or inside its tap window) or up. Returns true while any cap
 * is still moving, so the render loop keeps drawing.
 */
export function stepCaps(dtS: number, now: number): boolean {
  const { runtime, byPressKey } = useSim.getState();
  const down = new Set<string>();
  if (runtime) for (const key of byPressKey.keys()) if (isDown(key, now)) down.add(key);
  const k = 1 - Math.exp(-dtS * 40);
  let moving = false;
  for (const key of new Set([...caps.depth.keys(), ...down])) {
    const cur = caps.depth.get(key) ?? 0;
    const want = down.has(key) ? TRAVEL_MM : 0;
    const next = Math.abs(want - cur) < 0.01 ? want : cur + (want - cur) * k;
    if (next !== cur) {
      moving = true;
      caps.version++;
    }
    if (next === 0) caps.depth.delete(key);
    else caps.depth.set(key, next);
  }
  return moving || caps.depth.size > 0;
}

function isDown(pressKey: string, now: number): boolean {
  const { runtime, byPressKey } = useSim.getState();
  const input = byPressKey.get(pressKey);
  if (!runtime || !input) return false;
  return runtime.held.has(input.id) || (capHold.get(pressKey) ?? 0) > now;
}

export function clearCaps(): void {
  if (caps.depth.size) caps.version++;
  caps.depth.clear();
}
