// The combined device a simulation runs when several devices stand on one board: a macropad and the
// desktop display it drives, a keyboard and its mouse. Worked out from each device's parts (what it
// takes in, what it shows) and the links between them, so the simulator tests what the devices do
// together, not one of them alone: keys typed on the macropad show on the display, its knob changes
// what the display shows. Pure functions; CombinedDisplay.tsx draws the result.
import type { Build, BuildPart } from "../spec/types";
import type { SimEvent } from "./remote";

export interface SceneDevice {
  canvasId: string;
  name: string;
  build: Build | null;
}

export interface DeviceTraits {
  canvasId: string;
  buildId: string | null;
  /** "macropad", "desktop display": the device in a word or two. */
  noun: string;
  keys: number;
  buttons: number;
  knobs: number;
  sticks: number;
  pointer: boolean;
  touch: boolean;
  /** The screen parts that show something to the person (not status LEDs). */
  displays: { instanceId: string; label: string; kind: string }[];
  mcu: boolean;
}

export type FlowKind = "type" | "press" | "knob" | "point" | "host";

export interface Flow {
  kind: FlowKind;
  from: number;
  to: number | null;
  text: string;
}

export interface CombinedPlan {
  title: string;
  devices: DeviceTraits[];
  /** The device whose firmware the session runs: the one the person operates. */
  source: number;
  /** The device whose screen shows the result, when one has a screen. */
  display: number | null;
  flows: Flow[];
  /** One line: what this simulation tests. */
  testing: string;
}

const fn = (p: BuildPart) => p.card.primary_function ?? "";
const label = (p: BuildPart) => (p.label ?? p.card.display_name ?? "").toLowerCase();
/** Buttons that are there to flash or restart the board, not for the person to operate. */
const SYSTEM_BUTTON = /\b(?:boot|reset|rst|flash|program|dfu)\b/i;

const FILLER = /\b(?:an?|the|small|tiny|mini|little|compact|simple|desk|usb(?:-c)?|wireless|wired|bluetooth|portable|status|panel|\d+[- ]?(?:key|button|inch|in)s?|low-profile)\b/gi;

/** "4-key USB macropad for streaming controls" reads "macropad"; "small desktop status display panel" reads "desktop display". */
export function deviceNoun(name: string): string {
  const s = (name || "")
    .replace(/\b(?:stream\s*deck)\b/gi, "macropad")
    .split(/\s*[,;:(]\s*|\s+(?:with|that|for|which|to|using|plus|in|on)\s+/i)[0]
    .replace(FILLER, " ")
    .replace(/\s+/g, " ")
    .trim();
  const words = s.split(" ").filter(Boolean);
  return (words.slice(-3).join(" ") || name || "device").toLowerCase();
}

export function traitsOf(d: SceneDevice): DeviceTraits {
  const parts = d.build?.parts ?? [];
  const count = (f: (p: BuildPart) => boolean) => parts.filter(f).reduce((n, p) => n + Math.max(1, p.quantity ?? 1), 0);
  return {
    canvasId: d.canvasId,
    buildId: d.build?.build_id ?? null,
    noun: deviceNoun(d.name),
    keys: count((p) => fn(p) === "input.key" || fn(p) === "input.key_matrix"),
    buttons: count((p) => fn(p) === "input.button" && !SYSTEM_BUTTON.test(label(p))),
    knobs: count((p) => fn(p) === "input.rotary_encoder" || fn(p) === "input.potentiometer"),
    sticks: count((p) => fn(p) === "input.joystick"),
    pointer: parts.some((p) => fn(p) === "input.trackball" || /\b(?:optical|mouse)\b.*\bsensor\b|\bsensor\b.*\bmouse\b/.test(label(p))) || /\bmouse\b/.test(d.name.toLowerCase()),
    touch: parts.some((p) => fn(p) === "input.touch"),
    displays: parts
      .filter((p) => fn(p).startsWith("display.") && fn(p) !== "display.indicator_led")
      .map((p) => ({ instanceId: p.instance_id, label: p.label ?? p.card.display_name ?? "Display", kind: fn(p) })),
    mcu: parts.some((p) => fn(p) === "compute.mcu"),
  };
}

const operated = (t: DeviceTraits) => t.keys * 3 + t.knobs * 2 + t.buttons + t.sticks * 2 + (t.pointer ? 2 : 0);

function joinAnd(items: string[]): string {
  if (items.length <= 1) return items[0] ?? "";
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

/**
 * What the devices on one board do together. `link` is how they are connected ("a USB-C cable",
 * "Bluetooth"), when the project links say. Null for a board with one device.
 */
export function planCombined(title: string, devices: SceneDevice[], link: string | null = null): CombinedPlan | null {
  const traits = devices.filter((d) => d.build).map(traitsOf);
  if (traits.length < 2) return null;
  // the device the person operates runs the firmware: the most inputs, with a controller
  const order = traits.map((_, i) => i).sort((a, b) => operated(traits[b]) - operated(traits[a]) || Number(traits[b].mcu) - Number(traits[a].mcu));
  const source = order.find((i) => traits[i].mcu && operated(traits[i]) > 0) ?? order[0];
  const shown = traits.findIndex((t, i) => i !== source && t.displays.length > 0);
  const display = shown >= 0 ? shown : traits[source].displays.length ? source : null;
  const flows: Flow[] = [];
  const src = traits[source];
  if (display !== null && display !== source) {
    const dst = traits[display].noun;
    if (src.keys) flows.push({ kind: "type", from: source, to: display, text: `keys typed on the ${src.noun} show on the ${dst}` });
    else if (src.buttons) flows.push({ kind: "press", from: source, to: display, text: `buttons pressed on the ${src.noun} show on the ${dst}` });
    if (src.knobs) flows.push({ kind: "knob", from: source, to: display, text: `the ${src.noun}'s knob changes what the ${dst} shows` });
    if (src.sticks || src.pointer) flows.push({ kind: "point", from: source, to: display, text: `moving the ${src.noun} moves the cursor on the ${dst}` });
  }
  // devices with no screen between them feed one computer: a keyboard and its mouse
  for (const [i, t] of traits.entries()) {
    if (i === display || operated(t) === 0) continue;
    if (i === source && flows.length) continue;
    const what = t.pointer ? `clicks and moves on the ${t.noun}` : t.keys ? `keys typed on the ${t.noun}` : t.knobs ? `turns of the ${t.noun}'s knob` : `presses on the ${t.noun}`;
    flows.push({ kind: "host", from: i, to: null, text: `${what} reach the same computer` });
  }
  if (!flows.length) flows.push({ kind: "host", from: source, to: null, text: `the ${joinAnd(traits.map((t) => t.noun))} run together` });
  const via = link ? `, linked by ${link}` : "";
  const testing = `Testing the ${title.toLowerCase()}${via}: ${joinAnd(flows.map((f) => f.text))}.`;
  return { title, devices: traits, source, display, flows, testing };
}

/** What the display device shows while the combined device runs. */
export interface ComboScreen {
  /** What arrived as typed text, as a text box shows it. */
  text: string;
  /** The last control used on the source device, in plain words. */
  last: string | null;
  /** The knob's level, 0 to 100, once it has been turned. */
  level: number | null;
  levelLabel: string;
  presses: number;
}

export function emptyScreen(): ComboScreen {
  return { text: "", last: null, level: null, levelLabel: "Level", presses: 0 };
}

const LEVEL_STEP = 5;

/** Folds the running firmware's events into what the other device's screen shows. */
export function foldScreen(prev: ComboScreen, events: SimEvent[], limit = 240): ComboScreen {
  let { text, last, level, levelLabel, presses } = prev;
  for (const e of events) {
    if (e.type === "typed" && e.text) {
      for (const ch of e.text) text = ch === "\b" ? text.slice(0, -1) : text + ch;
    } else if (e.type === "input") {
      const name = e.label ?? e.name ?? "control";
      if (e.turn !== undefined && e.turn !== 0) {
        level = Math.max(0, Math.min(100, (level ?? 50) + Math.sign(e.turn) * LEVEL_STEP));
        levelLabel = name.replace(/\s*(?:knob|encoder|dial)\s*$/i, "") || "Level";
        last = `${name} turned ${e.turn > 0 ? "up" : "down"}`;
      } else if (e.value !== undefined) {
        last = `${name} at ${Math.round(e.value * 100)}%`;
      } else if (e.down) {
        presses += 1;
        last = `${name} pressed`;
      }
    }
  }
  return { text: text.slice(-limit), last, level, levelLabel: levelLabel || "Level", presses };
}

/** The flows the scene runs, for the build agent: the same lines the person reads. */
export function sceneContext(plan: CombinedPlan, names: string[]): { title: string; testing: string; devices: string[]; flows: string[] } {
  return { title: plan.title, testing: plan.testing, devices: names, flows: plan.flows.map((f) => f.text) };
}
