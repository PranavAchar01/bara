// What a device is laid out as on a shared canvas ("keyboard", "mouse", "handheld", ...), from its
// name or prompt. Pure, so the no-key sentence reader (bot/relation.ts) can use it too.
/** What a device is laid out as on a shared canvas. */
export type DeviceKind = "keyboard" | "mouse" | "handheld" | "display" | "dock" | "audio" | "board" | "device";

// The same words the engine's fallback reads (server/src/bara/intent.py DEVICE_KINDS).
const KIND_WORDS: [DeviceKind, string[]][] = [
  ["keyboard", ["keyboard", "numpad", "number pad", "keypad", "macropad", "macro pad"]],
  ["mouse", ["mouse", "trackball", "trackpad", "touchpad"]],
  ["handheld", ["handheld", "gameboy", "game boy", "console", "controller", "gamepad", "joystick", "remote"]],
  ["display", ["monitor", "desktop display", "status display"]],
  ["dock", ["dock", "stand", "charger", "charging pad", "hub"]],
  ["audio", ["headphones", "headset", "earbuds"]],
  ["board", ["dev board", "board"]],
];

const KINDS = new Set<string>([...KIND_WORDS.map(([k]) => k), "device"]);

export function isDeviceKind(k: string | null | undefined): k is DeviceKind {
  return !!k && KINDS.has(k);
}

function words(text: string): string {
  return ` ${text.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim()} `;
}

/** The kind a device is laid out as, from its name or prompt: the device word before any "for / to /
 *  with" ("a wireless mouse for a keyboard" is a mouse). Null when it names none. */
export function deviceKindOf(text: string | null | undefined): DeviceKind | null {
  if (!text) return null;
  const head = words(text).split(/ (?:for|to|with|beside|next to|that|alongside) /)[0] + " ";
  let best: { at: number; len: number; kind: DeviceKind } | null = null;
  for (const [kind, list] of KIND_WORDS)
    for (const w of list)
      for (const form of [w, `${w}s`, `${w}es`]) {
        const at = head.lastIndexOf(` ${form} `);
        if (at >= 0 && (!best || at > best.at || (at === best.at && w.length > best.len))) best = { at, len: w.length, kind };
      }
  return best?.kind ?? null;
}
