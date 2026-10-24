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
const GAME_KEYS: Record<string, string[]> = {
  UP: ["ArrowUp", "KeyW"],
  DOWN: ["ArrowDown", "KeyS"],
  LEFT: ["ArrowLeft", "KeyA"],
  RIGHT: ["ArrowRight", "KeyD"],
  A: ["KeyX", "KeyK", "Space"],
  B: ["KeyZ", "KeyJ"],
  X: ["KeyC", "KeyI"],
  Y: ["KeyV", "KeyU"],
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
  return inputs.find((i) => !i.code && (GAME_KEYS[i.name] ?? []).includes(code)) ?? null;
}
