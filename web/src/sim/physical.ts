// Which simulated input a physical keyboard key presses. A device with a keymap matches by ZMK
// key code (the physical Q key presses the input bound to `&kp Q`, wherever it sits); a device
// named by position matches by the conventional game controls.
import type { SimInput } from "./inputMap";

const CODE_TO_ZMK: Record<string, string> = {
  Space: "SPACE",
  Enter: "RET",
  NumpadEnter: "RET",
  Backspace: "BSPC",
  Tab: "TAB",
  Delete: "DEL",
  Comma: "COMMA",
  Period: "DOT",
  Slash: "FSLH",
  Backslash: "BSLH",
  Minus: "MINUS",
  Equal: "EQUAL",
  BracketLeft: "LBKT",
  BracketRight: "RBKT",
  Quote: "SQT",
  Backquote: "GRAVE",
  Semicolon: "SEMI",
  ShiftLeft: "LSHFT",
  ShiftRight: "RSHFT",
  ControlLeft: "LCTRL",
  ControlRight: "RCTRL",
  AltLeft: "LALT",
  AltRight: "RALT",
  MetaLeft: "LGUI",
  MetaRight: "RGUI",
  ArrowUp: "UP",
  ArrowDown: "DOWN",
  ArrowLeft: "LEFT",
  ArrowRight: "RIGHT",
};

/** ZMK code of a physical key (KeyboardEvent.code), or null for keys the keymap has no name for. */
export function zmkCodeOf(code: string): string | null {
  const letter = /^Key([A-Z])$/.exec(code);
  if (letter) return letter[1];
  const digit = /^Digit([0-9])$/.exec(code);
  if (digit) return `N${digit[1]}`;
  return CODE_TO_ZMK[code] ?? null;
}

/** Conventional controls for named inputs: arrows or WASD steer; X, K and Space are A; Z and J are B. */
export const GAME_KEYS: Record<string, string[]> = {
  UP: ["ArrowUp", "KeyW"],
  DOWN: ["ArrowDown", "KeyS"],
  LEFT: ["ArrowLeft", "KeyA"],
  RIGHT: ["ArrowRight", "KeyD"],
  A: ["KeyX", "KeyK", "Space"],
  B: ["KeyZ", "KeyJ"],
  X: ["KeyC", "KeyI"],
  Y: ["KeyV", "KeyU"],
  L: ["KeyQ"],
  R: ["KeyE"],
  START: ["Enter"],
  SELECT: ["ShiftRight", "Backspace"],
  RESET: ["KeyR"],
  BOOT: ["KeyP"],
};

/** The input a physical key presses on this device, or null. */
export function inputForKey(code: string, inputs: SimInput[]): SimInput | null {
  const zmk = zmkCodeOf(code);
  if (zmk) {
    const byCode = inputs.find((i) => i.code === zmk) ?? inputs.find((i) => i.code && i.code.replace(/^R/, "L") === zmk.replace(/^R/, "L") && /^[LR](SHFT|CTRL|ALT|GUI)$/.test(zmk));
    if (byCode) return byCode;
  }
  const named = inputs.filter((i) => !i.code && (GAME_KEYS[i.name] ?? []).includes(code));
  return named.find((i) => !i.spare) ?? named[0] ?? null;
}

const KEY_NAMES: Record<string, string> = {
  ArrowUp: "\u2191",
  ArrowDown: "\u2193",
  ArrowLeft: "\u2190",
  ArrowRight: "\u2192",
  Space: "Space",
  Enter: "Enter",
  ShiftRight: "Right Shift",
  Backspace: "Backspace",
};

/** A physical key code as printed on a keyboard: KeyX is X, ArrowUp is an arrow. */
export function keyName(code: string): string {
  return KEY_NAMES[code] ?? code.replace(/^Key|^Digit/, "");
}

/**
 * The on-screen legend for a handheld: each player control the device has, with the computer keys
 * that press it. The D-pad folds into one row; spare buttons (reset, boot) are left out.
 */
export function controlLegend(inputs: SimInput[]): { control: string; keys: string }[] {
  const names = new Set(inputs.filter((i) => !i.spare && !i.code && GAME_KEYS[i.name]).map((i) => i.name));
  const rows: { control: string; keys: string }[] = [];
  const pad = ["UP", "DOWN", "LEFT", "RIGHT"].filter((n) => names.has(n));
  if (pad.length) rows.push({ control: "D-pad", keys: "Arrows or WASD" });
  for (const n of ["A", "B", "X", "Y", "L", "R", "START", "SELECT"]) {
    if (names.has(n)) rows.push({ control: n === "START" ? "Start" : n === "SELECT" ? "Select" : n, keys: GAME_KEYS[n].map(keyName).join(" or ") });
  }
  return rows;
}
