// A real keyboard pressing the simulated one.
import type { SimDevice, SimKey } from "./device";

/** The keys to hold, in order, for a real key: its own position on the base layer, else a layer key plus the position on that layer. */
export function chordFor(device: SimDevice, name: string): string[] | null {
  const alias: Record<string, string[]> = { LSHFT: ["LSHFT", "RSHFT"], RSHFT: ["RSHFT", "LSHFT"], LCTRL: ["LCTRL", "RCTRL"], RCTRL: ["RCTRL", "LCTRL"], LALT: ["LALT", "RALT"], RALT: ["RALT", "LALT"], LGUI: ["LGUI", "RGUI"], RGUI: ["RGUI", "LGUI"] };
  const names = alias[name] ?? [name];
  const tapKey = (b: SimDevice["layers"][number]["bindings"][number] | undefined) => (b?.kind === "kp" ? b.key : b?.kind === "lt" || b?.kind === "mt" ? b.key : null);
  const byPos = new Map(device.keys.map((k) => [k.pos, k]));
  for (const n of names) {
    const base = device.layers[0]?.bindings.findIndex((b) => tapKey(b) === n || (b.kind === "mt" && b.mod === n));
    if (base !== undefined && base >= 0 && byPos.has(base)) return [(byPos.get(base) as SimKey).id];
  }
  for (let l = 1; l < device.layers.length; l++) {
    const pos = device.layers[l].bindings.findIndex((b) => names.includes(tapKey(b) ?? ""));
    const layerKey = device.layers[0]?.bindings.findIndex((b) => (b.kind === "mo" || b.kind === "lt") && b.layer === l);
    if (pos >= 0 && layerKey !== undefined && layerKey >= 0 && byPos.has(pos) && byPos.has(layerKey)) {
      return [(byPos.get(layerKey) as SimKey).id, (byPos.get(pos) as SimKey).id];
    }
  }
  return null;
}
