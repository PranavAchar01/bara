// Reads the build's firmware source (SPEC 4.9) into what the simulator runs: keymap layers,
// Kconfig flags, the matrix transform, and the peripherals the code drives. Pure, no DOM.
import type { Firmware } from "../spec/types";
import { qmkKeyName } from "./keys";

export type Binding =
  | { kind: "kp"; key: string }
  | { kind: "mo"; layer: number }
  | { kind: "to"; layer: number }
  | { kind: "tog"; layer: number }
  | { kind: "lt"; layer: number; key: string }
  | { kind: "mt"; mod: string; key: string }
  | { kind: "bt"; action: string; profile?: number }
  | { kind: "out"; action: string }
  | { kind: "trans" }
  | { kind: "none" }
  | { kind: "other"; raw: string };

export interface KeymapLayer {
  name: string;
  bindings: Binding[];
}

/** One encoder's two directions, from sensor-bindings (ZMK) or the framework default. */
export interface EncoderBinding {
  cw: string;
  ccw: string;
}

export interface ParsedKeymap {
  layers: KeymapLayer[];
  encoders: EncoderBinding[];
}

function stripComments(src: string): string {
  return src.replace(/\/\*[\s\S]*?\*\//g, " ").replace(/\/\/[^\n]*/g, " ");
}

function defines(src: string): Map<string, string> {
  const out = new Map<string, string>();
  for (const m of src.matchAll(/^\s*#define\s+([A-Za-z_]\w*)\s+(\S+)/gm)) out.set(m[1], m[2]);
  return out;
}

function num(tok: string | undefined, defs: Map<string, string>): number {
  if (tok === undefined) return 0;
  const v = defs.get(tok) ?? tok;
  const n = Number.parseInt(v, 10);
  return Number.isFinite(n) ? n : 0;
}

/** "&kp Q &mo 1 &trans" -> bindings. Behaviour arguments are the tokens up to the next "&". */
export function parseZmkBindings(body: string, defs = new Map<string, string>()): Binding[] {
  const out: Binding[] = [];
  for (const chunk of body.split("&").slice(1)) {
    const [name, ...args] = chunk.trim().split(/\s+/).filter(Boolean);
    if (!name) continue;
    switch (name) {
      case "kp":
        out.push({ kind: "kp", key: args[0] ?? "NONE" });
        break;
      case "mo":
      case "to":
      case "tog":
        out.push({ kind: name, layer: num(args[0], defs) });
        break;
      case "lt":
        out.push({ kind: "lt", layer: num(args[0], defs), key: args[1] ?? "NONE" });
        break;
      case "mt":
        out.push({ kind: "mt", mod: args[0] ?? "LSHFT", key: args[1] ?? "NONE" });
        break;
      case "bt":
        out.push({ kind: "bt", action: args[0] ?? "BT_SEL", profile: args[1] !== undefined ? num(args[1], defs) : undefined });
        break;
      case "out":
        out.push({ kind: "out", action: args[0] ?? "OUT_TOG" });
        break;
      case "trans":
        out.push({ kind: "trans" });
        break;
      case "none":
        out.push({ kind: "none" });
        break;
      default:
        out.push({ kind: "other", raw: `&${[name, ...args].join(" ")}` });
    }
  }
  return out;
}

/** The layers of a ZMK .keymap: every child of the "zmk,keymap" node, in source order. */
export function parseZmkKeymap(src: string): ParsedKeymap {
  const defs = defines(src);
  const text = stripComments(src);
  const layers: KeymapLayer[] = [];
  const encoders: EncoderBinding[] = [];
  const start = text.search(/compatible\s*=\s*"zmk,keymap"/);
  if (start < 0) return { layers, encoders };
  // only the keymap node: combos and macros further down have bindings too
  let end = start;
  for (let depth = 1; end < text.length && depth > 0; end++) {
    if (text[end] === "{") depth++;
    else if (text[end] === "}") depth--;
  }
  for (const m of text.slice(start, end).matchAll(/([A-Za-z_][\w-]*)\s*\{([^{}]*)\}/g)) {
    const body = m[2];
    const b = /(?<![-\w])bindings\s*=\s*<([\s\S]*?)>\s*;/.exec(body);
    if (!b) continue;
    const label = /(?:display-name|label)\s*=\s*"([^"]*)"/.exec(body)?.[1];
    layers.push({ name: label ?? m[1].replace(/_layer$/, ""), bindings: parseZmkBindings(b[1], defs) });
    const s = /sensor-bindings\s*=\s*<([\s\S]*?)>\s*;/.exec(body);
    if (s && layers.length === 1) {
      for (const chunk of s[1].split("&").slice(1)) {
        const [, cw, ccw] = chunk.trim().split(/\s+/);
        if (cw && ccw) encoders.push({ cw, ccw });
      }
    }
  }
  return { layers, encoders };
}

function splitArgs(s: string): string[] {
  const out: string[] = [];
  let depth = 0;
  let cur = "";
  for (const ch of s) {
    if (ch === "(") depth++;
    if (ch === ")") depth--;
    if (ch === "," && depth === 0) {
      out.push(cur.trim());
      cur = "";
    } else cur += ch;
  }
  if (cur.trim()) out.push(cur.trim());
  return out;
}

const QMK_MOD_TAP: Record<string, string> = {
  LSFT_T: "LSHFT",
  RSFT_T: "RSHFT",
  LCTL_T: "LCTRL",
  RCTL_T: "RCTRL",
  LALT_T: "LALT",
  RALT_T: "RALT",
  LGUI_T: "LGUI",
  RGUI_T: "RGUI",
};

function qmkBinding(tok: string, layerIndex: Map<string, number>): Binding {
  const layer = (s: string) => layerIndex.get(s.trim()) ?? (Number.parseInt(s, 10) || 0);
  if (tok === "_______" || tok === "KC_TRNS" || tok === "KC_TRANSPARENT") return { kind: "trans" };
  if (tok === "XXXXXXX" || tok === "KC_NO") return { kind: "none" };
  const call = /^(\w+)\((.*)\)$/.exec(tok);
  if (call) {
    const [, fn, inner] = call;
    const args = splitArgs(inner);
    if (fn === "MO") return { kind: "mo", layer: layer(args[0]) };
    if (fn === "TO") return { kind: "to", layer: layer(args[0]) };
    if (fn === "TG") return { kind: "tog", layer: layer(args[0]) };
    if (fn === "LT") return { kind: "lt", layer: layer(args[0]), key: qmkKeyName(args[1] ?? "KC_NO") };
    if (QMK_MOD_TAP[fn]) return { kind: "mt", mod: QMK_MOD_TAP[fn], key: qmkKeyName(args[0] ?? "KC_NO") };
    if (fn === "S" || fn === "LSFT") return { kind: "kp", key: `LS(${qmkKeyName(args[0] ?? "KC_NO")})` };
    return { kind: "other", raw: tok };
  }
  if (tok.startsWith("KC_")) return { kind: "kp", key: qmkKeyName(tok) };
  return { kind: "other", raw: tok };
}

/** Layers of a QMK keymap.c: each "[N] = LAYOUT...(...)" entry of keymaps[]. */
export function parseQmkKeymap(src: string): ParsedKeymap {
  const text = stripComments(src);
  const layerIndex = new Map<string, number>();
  const en = /enum\s+\w*layers?\w*\s*\{([^}]*)\}/.exec(text);
  if (en) {
    let i = 0;
    for (const raw of en[1].split(",")) {
      const [name, val] = raw.split("=").map((x) => x.trim());
      if (!name) continue;
      if (val !== undefined) i = Number.parseInt(val, 10) || 0;
      layerIndex.set(name, i++);
    }
  }
  const layers: KeymapLayer[] = [];
  const re = /\[\s*(\w+)\s*\]\s*=\s*LAYOUT\w*\s*\(/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text))) {
    let depth = 1;
    let i = re.lastIndex;
    for (; i < text.length && depth > 0; i++) {
      if (text[i] === "(") depth++;
      else if (text[i] === ")") depth--;
    }
    const body = text.slice(re.lastIndex, i - 1);
    const idx = layerIndex.get(m[1]) ?? (Number.parseInt(m[1], 10) || layers.length);
    layers[idx] = { name: m[1].replace(/^_/, "").toLowerCase(), bindings: splitArgs(body).map((t) => qmkBinding(t, layerIndex)) };
  }
  return { layers: layers.filter(Boolean), encoders: [] };
}

/** CONFIG_X=y lines. */
export function parseKconfig(src: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const m of src.matchAll(/^\s*(CONFIG_\w+)\s*=\s*(.+?)\s*$/gm)) out[m[1]] = m[2].replace(/^"|"$/g, "");
  return out;
}

/** The "zmk,matrix-transform" map: binding position i -> [row, col]. */
export function parseMatrixTransform(src: string): [number, number][] | null {
  const m = /map\s*=\s*<([^>]*)>/.exec(stripComments(src));
  if (!m) return null;
  const out: [number, number][] = [];
  for (const rc of m[1].matchAll(/RC\(\s*(\d+)\s*,\s*(\d+)\s*\)/g)) out.push([Number(rc[1]), Number(rc[2])]);
  return out.length ? out : null;
}

/** Sensors and displays a gadget's code drives, and how often it reads them. */
export interface GadgetConfig {
  sensors: string[];
  displays: string[];
  encoders: number;
  updateMs: number;
}

export function parseGadget(fw: Firmware): GadgetConfig {
  const src = fw.files.map((f) => f.content ?? "").join("\n");
  const drivers = (fw.drivers ?? []).map((d) => `${d.part_id} ${d.library} ${d.include ?? ""}`).join(" ");
  const all = `${src}\n${drivers}`.toLowerCase();
  const sensors: string[] = [];
  for (const s of ["bme280", "bmp280", "sht31", "aht20", "dht22", "scd40"]) if (all.includes(s)) sensors.push(s);
  const displays: string[] = [];
  for (const d of ["sh1106", "ssd1306", "st7789"]) if (all.includes(d)) displays.push(d);
  const encoders = (all.match(/rotary_encoder|encoder\.h/g) ?? []).length;
  let updateMs = 10_000;
  const every = /every\s+(\d+(?:\.\d+)?)\s*(ms|s|sec|seconds?)\b/.exec(all);
  const interval = /update_interval:\s*(\d+(?:\.\d+)?)\s*(ms|s|min)/.exec(all);
  const delay = /delay\(\s*(\d+)\s*\)/.exec(all);
  if (interval) updateMs = Number(interval[1]) * (interval[2] === "ms" ? 1 : interval[2] === "min" ? 60_000 : 1000);
  else if (every) updateMs = Number(every[1]) * (every[2] === "ms" ? 1 : 1000);
  else if (delay) updateMs = Number(delay[1]);
  return { sensors, displays, encoders, updateMs: Math.max(250, updateMs) };
}

/** The keymap file of a firmware, by framework. */
export function keymapFile(fw: Firmware) {
  return (
    fw.files.find((f) => f.path.endsWith(".keymap")) ??
    fw.files.find((f) => /keymap\.c$/.test(f.path)) ??
    null
  );
}

export function parseKeymapSource(path: string, src: string): ParsedKeymap {
  if (path.endsWith(".c") || /\bLAYOUT\w*\s*\(/.test(src)) return parseQmkKeymap(src);
  return parseZmkKeymap(src);
}

// ZMK's Corne (42 key) default keymap from zmk-config, in physical row order. Used when the build's
// keymap file has no bindings in it (the template ships a stub): it is what the board runs by default.
const CORNE_DEFAULT = `
/ { keymap { compatible = "zmk,keymap";
default_layer { display-name = "Base"; bindings = <
&kp TAB   &kp Q &kp W &kp E &kp R &kp T   &kp Y &kp U &kp I &kp O &kp P &kp BSPC
&kp LCTRL &kp A &kp S &kp D &kp F &kp G   &kp H &kp J &kp K &kp L &kp SEMI &kp SQT
&kp LSHFT &kp Z &kp X &kp C &kp V &kp B   &kp N &kp M &kp COMMA &kp DOT &kp FSLH &kp ESC
&kp LGUI &mo 1 &kp SPACE   &kp RET &mo 2 &kp RALT
>; };
lower_layer { display-name = "Lower"; bindings = <
&kp TAB   &kp N1 &kp N2 &kp N3 &kp N4 &kp N5   &kp N6 &kp N7 &kp N8 &kp N9 &kp N0 &kp BSPC
&kp LCTRL &bt BT_CLR &bt BT_SEL 0 &bt BT_SEL 1 &bt BT_SEL 2 &bt BT_SEL 3   &kp LEFT &kp DOWN &kp UP &kp RIGHT &trans &trans
&kp LSHFT &trans &trans &trans &trans &trans   &trans &trans &trans &trans &trans &trans
&kp LGUI &trans &kp SPACE   &kp RET &trans &kp RALT
>; };
raise_layer { display-name = "Raise"; bindings = <
&kp TAB   &kp EXCL &kp AT &kp HASH &kp DOLLAR &kp PRCNT   &kp CARET &kp AMPS &kp ASTRK &kp LPAR &kp RPAR &kp BSPC
&kp LCTRL &trans &trans &trans &trans &trans   &kp MINUS &kp EQUAL &kp LBKT &kp RBKT &kp BSLH &kp GRAVE
&kp LSHFT &trans &trans &trans &trans &trans   &kp UNDER &kp PLUS &kp LBRC &kp RBRC &kp PIPE &kp TILDE
&kp LGUI &trans &kp SPACE   &kp RET &trans &kp RALT
>; };
}; };`;

const GENERIC_KEYS = (
  "Q W E R T Y U I O P A S D F G H J K L SEMI Z X C V B N M COMMA DOT FSLH " +
  "N1 N2 N3 N4 N5 N6 N7 N8 N9 N0 MINUS EQUAL LBKT RBKT BSLH SQT GRAVE"
).split(" ");
const GENERIC_THUMBS = ["LGUI", "SPACE", "LSHFT", "RET", "BSPC", "LALT", "LCTRL", "TAB"];

/** The keymap a board runs when its source has none: ZMK's Corne default for 42 keys, else the generator's order. */
export function defaultKeymap(keyCount: number, thumbs: boolean[]): ParsedKeymap {
  if (keyCount === 42) return parseZmkKeymap(CORNE_DEFAULT);
  let n = 0;
  let t = 0;
  const bindings: Binding[] = thumbs.map((thumb) =>
    thumb ? { kind: "kp", key: GENERIC_THUMBS[t++ % GENERIC_THUMBS.length] } : { kind: "kp", key: GENERIC_KEYS[n++ % GENERIC_KEYS.length] },
  );
  return { layers: [{ name: "Base", bindings }], encoders: [] };
}
