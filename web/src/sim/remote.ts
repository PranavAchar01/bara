// The engine's firmware simulator (POST /v1/builds/{id}/sim/...): the build's firmware compiled for
// its controller, run in an emulator (or the host test harness when the chip has no model), with
// the device's inputs and outputs named in plain words, the test catalog and the agent chat.
import { getRest } from "../net/client";
import { authHeaders, serverUrl } from "../net/mode";
import type { InputMap } from "./inputMap";

export type SimInputKind = "key" | "mkey" | "button" | "switch" | "encoder" | "axis" | "pot" | "sensor" | "power";

export interface RemoteInput {
  id: string;
  label: string;
  kind: SimInputKind;
  instance_id: string;
  index?: number;
  pin?: string;
  code?: string | null;
  matters?: boolean;
  /** Sensors: the measured quantity, its unit, the part's physical range and its resting value. */
  quantity?: string;
  unit?: string;
  min?: number;
  max?: number;
  default?: number;
}

export interface RemoteOutput {
  id: string;
  label: string;
  kind: string;
  instance_id: string;
  pin?: string;
}

export interface SimIo {
  device: { name?: string };
  kind: string;
  mcu: { board_id: string; label: string; family: string; core?: string; emulator?: string; instance_id?: string };
  inputs: RemoteInput[];
  outputs: RemoteOutput[];
  power: {
    switch: { id: string; label: string; instance_id: string } | null;
    battery: { instance_id: string; name: string } | null;
    charger: { instance_id: string; name: string } | null;
    regulator: { instance_id: string; name: string } | null;
  };
  unsimulated: { instance_id: string; label: string; reason?: string }[];
  pins_source: string;
  pins_used: Record<string, string>;
  labels_by: "ai" | "rules";
  labels_model?: string | null;
  try_first?: string;
}

export interface CompileStep {
  status: "ok" | "failed" | "unavailable";
  compiler?: string;
  command?: string;
  log?: string;
  seconds?: number;
  exit_code?: number;
  size?: { text: number; data: number; bss: number; image: number };
  load_address?: string;
  entry?: string;
  sha256?: string;
}

export interface SimFirmware {
  status: "ok" | "failed";
  mode: "emulated" | "host" | "none";
  board: { id: string; label: string; family: string; emulator?: string };
  target: CompileStep;
  host: CompileStep;
  files: string[];
  notes: string[];
  downloads: Record<string, string>;
}

export interface SimEvent {
  seq: number;
  t_ms: number;
  type: "serial" | "typed" | "hid" | "gpio" | "tone" | "input" | "power" | "fault";
  text?: string;
  report?: string;
  pin?: number;
  level?: number;
  name?: string;
  label?: string;
  down?: boolean;
  turn?: number;
  value?: number;
  on?: boolean;
}

export interface SimSnap {
  mode: "emulated" | "host";
  powered: boolean;
  t_ms: number;
  screen: string[];
  hid: string;
  leds: { id: string; label: string; kind?: string; on: boolean }[];
  inputs: { closed: Record<string, boolean>; axes: Record<string, number> };
  events: SimEvent[];
  wave: Record<string, { name: string; edges: [number, number][] }>;
  seq: number;
  /** Set while the chip is held in its bootloader (reset with the boot button down). */
  bootloader?: boolean;
  /** The display's pixels as the firmware drew them: 2 bits a pixel, base64. Null when the firmware draws no pixels. */
  fb?: { w: number; h: number; b64: string } | null;
}

export interface SimTest {
  id: string;
  group: "firmware" | "emulation" | "pinmap" | "ngspice" | "kicad";
  violations?: { severity?: string; description?: string; type?: string }[];
  name: string;
  status: "not_run" | "pass" | "fail" | "warn" | "skip" | "unavailable";
  summary?: string;
  log?: string | string[];
  numbers?: Record<string, number | string>;
  assumptions?: string[];
}

export interface ChatEntry {
  role: "user" | "agent";
  text: string;
  changes?: Record<string, unknown>;
  rebuilt?: boolean;
  by?: string;
  build_status?: string | null;
  tests?: { passed: number; failed: number } | null;
  surface_ops?: SurfaceOp[];
}

/** A change to the play surface the agent asked for; the server has already checked it against the real parts. */
export interface SurfaceOp {
  op: "show" | "hide" | "rename" | "lead" | "set";
  input_id: string;
  label?: string;
  value?: number;
}

export interface SimConfig {
  blink_ms: number;
  debounce_ms: number;
  tone_ms: number;
  axis_deadzone: number;
  led_on_press: boolean;
  screen_aspect: number;
  labels: Record<string, string>;
}

export interface SimScene {
  title: string;
  testing: string;
  devices: string[];
  flows: string[];
}

export interface SimViewData {
  build_id: string;
  prompt: string | null;
  io: SimIo;
  firmware: SimFirmware;
  config: SimConfig;
  tests: SimTest[];
  chat: ChatEntry[];
  labels_note: string;
  snapshot: SimSnap | null;
}

export type ControlKind = "key" | "button" | "toggle" | "knob" | "stick" | "slider";
export type OutputShow = "screen" | "led" | "led_strip" | "buzzer" | "motor" | "console";

/** One control of the play surface: always one real input of the build. */
export interface SurfaceControl {
  input_id: string;
  kind: SimInputKind;
  control: ControlKind;
  label: string;
  unit: string;
  group: string;
  instance_id?: string;
  index?: number;
  min?: number;
  max?: number;
  default?: number;
}

export interface SurfaceOutput {
  output_id: string;
  kind: string;
  show: OutputShow;
  label: string;
}

export interface Surface {
  controls: SurfaceControl[];
  outputs: SurfaceOutput[];
  lead: string;
  sig: string;
  by: "model" | "parts";
}

export type InputAction = "press" | "release" | "tap" | "turn" | "axis" | "sensor" | "power" | "reset";

async function call<T>(method: "GET" | "POST", path: string, body?: unknown): Promise<T> {
  const res = await getRest().request<T>(method, path, body);
  if (!res.ok) throw new Error(res.error.message || `Request failed (${res.status})`);
  return res.body;
}

const base = (id: string) => `/v1/builds/${encodeURIComponent(id)}/sim`;

/** Names the workspace already gave each control from where it sits (UP, A, START), keyed the way the engine keys them. */
export function clientNames(map: InputMap | null): { names: Record<string, string>; codes: Record<string, string> } {
  const names: Record<string, string> = {};
  const codes: Record<string, string> = {};
  for (const i of map?.inputs ?? []) {
    const key = `${i.instanceId}#${i.index}`;
    names[key] = i.name;
    if (i.code) codes[key] = i.code;
  }
  return { names, codes };
}

export const sim = {
  /** `scene`: the combined device this build stands in, so the build agent knows what is tested. */
  start: (id: string, map: InputMap | null, scene: SimScene | null = null, screenAspect: number | null = null) =>
    call<{ sim: SimViewData }>("POST", `${base(id)}/start`, {
      ...clientNames(map),
      ...(scene ? { scene } : {}),
      ...(screenAspect ? { config: { screen_aspect: screenAspect } } : {}),
    }).then((r) => r.sim),
  config: (id: string, config: Partial<SimConfig>) => call<{ sim: SimViewData }>("POST", `${base(id)}/config`, config).then((r) => r.sim),
  view: (id: string) => call<{ sim: SimViewData }>("GET", base(id)).then((r) => r.sim),
  input: (id: string, body: { id: string; action: InputAction; value?: number | boolean; since: number }) =>
    call<{ snapshot: SimSnap }>("POST", `${base(id)}/input`, body).then((r) => r.snapshot),
  run: (id: string, ms: number, since: number) => call<{ snapshot: SimSnap }>("POST", `${base(id)}/run`, { ms, since }).then((r) => r.snapshot),
  reset: (id: string) => call<{ sim: SimViewData }>("POST", `${base(id)}/reset`, {}).then((r) => r.sim),
  tests: (id: string, ids?: string[]) => call<{ results: SimTest[]; sim: SimViewData }>("POST", `${base(id)}/tests`, ids ? { ids } : {}),
  surface: (id: string, refresh = false) => call<{ surface: Surface }>("POST", `${base(id)}/surface`, { refresh }).then((r) => r.surface),
  chat: (id: string, message: string) => call<{ reply: ChatEntry; sim: SimViewData }>("POST", `${base(id)}/chat`, { message }),
  async source(id: string, name: string): Promise<string> {
    const res = await fetch(serverUrl(`${base(id)}/source/${encodeURIComponent(name)}`), { headers: authHeaders() });
    if (!res.ok) throw new Error(`No source ${name}`);
    return res.text();
  },
};

/** One line of the terminal for an event, or null for events the terminal leaves out. */
export function terminalLine(e: SimEvent): { text: string; tone: "out" | "in" | "hid" | "sys" } | null {
  const t = `${(e.t_ms / 1000).toFixed(3)}s`;
  switch (e.type) {
    case "serial":
      return e.text?.startsWith("HID") ? null : { text: `${t}  ${e.text ?? ""}`, tone: "out" };
    case "typed":
      return null;
    case "hid":
      return { text: `${t}  usb  ${e.report ?? ""}`, tone: "hid" };
    case "input": {
      const what = e.turn !== undefined ? `turned ${e.turn > 0 ? "clockwise" : "anticlockwise"}` : e.value !== undefined ? `moved to ${e.value.toFixed(2)}` : e.down ? "pressed" : "released";
      return { text: `${t}  > ${e.label ?? e.name ?? ""} ${what}`, tone: "in" };
    }
    case "power":
      return { text: `${t}  ${e.text ?? `power ${e.on ? "on" : "off"}`}`, tone: "sys" };
    case "fault":
      return { text: `${t}  fault: ${e.text ?? ""}`, tone: "sys" };
    default:
      return null;
  }
}

/** What the firmware typed over USB, as a person would see it in a text box: letters appear, backspace erases, enter breaks the line. */
export function typedText(events: SimEvent[], prev = "", limit = 600): string {
  let out = prev;
  for (const e of events) {
    if (e.type !== "typed" || !e.text) continue;
    for (const ch of e.text) out = ch === "\b" ? out.slice(0, -1) : out + ch;
  }
  return out.slice(-limit);
}
