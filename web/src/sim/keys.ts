// Key names as ZMK spells them (dt-bindings/zmk/keys.h), with what each one types on a US host.
// QMK keycodes are folded onto the same names so one machine runs both keymaps.

export interface KeyInfo {
  /** Short legend for the keycap. */
  label: string;
  /** What the host types, unshifted and shifted; null for keys that type nothing. */
  char: string | null;
  shifted?: string;
  modifier?: "shift" | "ctrl" | "alt" | "gui";
}

const T: Record<string, KeyInfo> = {};

function put(names: string[], info: KeyInfo) {
  for (const n of names) T[n] = info;
}

for (const c of "ABCDEFGHIJKLMNOPQRSTUVWXYZ") put([c], { label: c, char: c.toLowerCase(), shifted: c });
const DIGIT_SHIFT = ")!@#$%^&*(";
for (let d = 0; d <= 9; d++) put([`N${d}`, `NUMBER_${d}`], { label: String(d), char: String(d), shifted: DIGIT_SHIFT[d] });

put(["SPACE", "SPC"], { label: "Space", char: " ", shifted: " " });
put(["RET", "ENTER", "RETURN", "ENT"], { label: "Enter", char: "\n", shifted: "\n" });
put(["BSPC", "BACKSPACE"], { label: "Bksp", char: "\b", shifted: "\b" });
put(["TAB"], { label: "Tab", char: "\t", shifted: "\t" });
put(["ESC", "ESCAPE"], { label: "Esc", char: null });
put(["DEL", "DELETE"], { label: "Del", char: null });
put(["LEFT", "LEFT_ARROW"], { label: "←", char: null });
put(["RIGHT", "RIGHT_ARROW"], { label: "→", char: null });
put(["UP", "UP_ARROW"], { label: "↑", char: null });
put(["DOWN", "DOWN_ARROW"], { label: "↓", char: null });
put(["HOME"], { label: "Home", char: null });
put(["END"], { label: "End", char: null });
put(["PG_UP"], { label: "PgUp", char: null });
put(["PG_DN"], { label: "PgDn", char: null });
put(["CAPS", "CAPSLOCK"], { label: "Caps", char: null });

put(["LSHFT", "LSHIFT", "LEFT_SHIFT", "RSHFT", "RSHIFT", "RIGHT_SHIFT"], { label: "Shift", char: null, modifier: "shift" });
put(["LCTRL", "LEFT_CONTROL", "RCTRL", "RIGHT_CONTROL"], { label: "Ctrl", char: null, modifier: "ctrl" });
put(["LALT", "LEFT_ALT", "RALT", "RIGHT_ALT"], { label: "Alt", char: null, modifier: "alt" });
put(["LGUI", "LEFT_GUI", "LCMD", "LWIN", "RGUI", "RIGHT_GUI", "RCMD", "RWIN"], { label: "Gui", char: null, modifier: "gui" });

const SYMBOLS: [string[], string, string, string][] = [
  [["SEMI", "SEMICOLON"], ";", ":", ";"],
  [["SQT", "APOS", "SINGLE_QUOTE"], "'", '"', "'"],
  [["COMMA"], ",", "<", ","],
  [["DOT", "PERIOD"], ".", ">", "."],
  [["FSLH", "SLASH"], "/", "?", "/"],
  [["MINUS"], "-", "_", "-"],
  [["EQUAL"], "=", "+", "="],
  [["LBKT", "LEFT_BRACKET"], "[", "{", "["],
  [["RBKT", "RIGHT_BRACKET"], "]", "}", "]"],
  [["BSLH", "BACKSLASH"], "\\", "|", "\\"],
  [["GRAVE"], "`", "~", "`"],
];
for (const [names, c, s, label] of SYMBOLS) put(names, { label, char: c, shifted: s });

// keys that are a shifted symbol in their own right
const SHIFTED: [string[], string][] = [
  [["EXCL", "EXCLAMATION"], "!"],
  [["AT", "AT_SIGN"], "@"],
  [["HASH", "POUND"], "#"],
  [["DOLLAR", "DLLR"], "$"],
  [["PRCNT", "PERCENT"], "%"],
  [["CARET"], "^"],
  [["AMPS", "AMPERSAND"], "&"],
  [["ASTRK", "STAR", "ASTERISK"], "*"],
  [["LPAR", "LEFT_PARENTHESIS"], "("],
  [["RPAR", "RIGHT_PARENTHESIS"], ")"],
  [["UNDER", "UNDERSCORE"], "_"],
  [["PLUS"], "+"],
  [["LBRC", "LEFT_BRACE"], "{"],
  [["RBRC", "RIGHT_BRACE"], "}"],
  [["PIPE"], "|"],
  [["TILDE"], "~"],
  [["COLON"], ":"],
  [["DQT", "DOUBLE_QUOTES"], '"'],
  [["LT", "LESS_THAN"], "<"],
  [["GT", "GREATER_THAN"], ">"],
  [["QMARK", "QUESTION"], "?"],
];
for (const [names, c] of SHIFTED) put(names, { label: c, char: c, shifted: c });

put(["C_VOL_UP", "C_VOLUME_UP"], { label: "Vol+", char: null });
put(["C_VOL_DN", "C_VOLUME_DOWN"], { label: "Vol−", char: null });
put(["C_MUTE"], { label: "Mute", char: null });
put(["C_PP", "C_PLAY_PAUSE"], { label: "Play", char: null });
put(["C_NEXT"], { label: "Next", char: null });
put(["C_PREV"], { label: "Prev", char: null });
for (let f = 1; f <= 12; f++) put([`F${f}`], { label: `F${f}`, char: null });

/** A ZMK key name (or a modifier-wrapped one like LS(N1)) to what it types. */
export function keyInfo(name: string): KeyInfo {
  const wrapped = /^(LS|RS|LC|RC|LA|RA|LG|RG)\((.+)\)$/.exec(name);
  if (wrapped) {
    const inner = keyInfo(wrapped[2]);
    if (wrapped[1].endsWith("S")) return { label: inner.shifted ?? inner.label, char: inner.shifted ?? inner.char, shifted: inner.shifted };
    return { label: `${wrapped[1][0] === "L" ? "" : "R"}${wrapped[1][1]}-${inner.label}`, char: null };
  }
  return T[name] ?? { label: name.replace(/^C_/, "").slice(0, 5), char: null };
}

// QMK basic keycodes whose ZMK name differs from KC_ stripped
const QMK_ALIAS: Record<string, string> = {
  SPC: "SPACE",
  ENT: "RET",
  ENTER: "RET",
  BSPC: "BSPC",
  LSFT: "LSHFT",
  RSFT: "RSHFT",
  LCTL: "LCTRL",
  RCTL: "RCTRL",
  LOPT: "LALT",
  ROPT: "RALT",
  LCMD: "LGUI",
  RCMD: "RGUI",
  SCLN: "SEMI",
  QUOT: "SQT",
  COMM: "COMMA",
  SLSH: "FSLH",
  MINS: "MINUS",
  EQL: "EQUAL",
  LBRC: "LBKT",
  RBRC: "RBKT",
  BSLS: "BSLH",
  GRV: "GRAVE",
  EXLM: "EXCL",
  DLR: "DOLLAR",
  PERC: "PRCNT",
  CIRC: "CARET",
  AMPR: "AMPS",
  ASTR: "ASTRK",
  LPRN: "LPAR",
  RPRN: "RPAR",
  UNDS: "UNDER",
  LCBR: "LBRC",
  RCBR: "RBRC",
  TILD: "TILDE",
  COLN: "COLON",
  DQUO: "DQT",
  QUES: "QMARK",
  VOLU: "C_VOL_UP",
  VOLD: "C_VOL_DN",
  MUTE: "C_MUTE",
  MPLY: "C_PP",
  LEFT: "LEFT",
  RGHT: "RIGHT",
  RIGHT: "RIGHT",
  UP: "UP",
  DOWN: "DOWN",
};

/** KC_A -> A, KC_1 -> N1, KC_SPC -> SPACE. */
export function qmkKeyName(kc: string): string {
  const k = kc.replace(/^KC_/, "");
  if (/^[0-9]$/.test(k)) return `N${k}`;
  return QMK_ALIAS[k] ?? k;
}

/** Browser KeyboardEvent.code -> the ZMK key name it stands for, so a real keyboard can press the simulated one. */
export function codeToKeyName(code: string): string | null {
  let m = /^Key([A-Z])$/.exec(code);
  if (m) return m[1];
  m = /^Digit([0-9])$/.exec(code);
  if (m) return `N${m[1]}`;
  const map: Record<string, string> = {
    Space: "SPACE",
    Enter: "RET",
    Backspace: "BSPC",
    Tab: "TAB",
    ShiftLeft: "LSHFT",
    ShiftRight: "RSHFT",
    ControlLeft: "LCTRL",
    ControlRight: "RCTRL",
    AltLeft: "LALT",
    AltRight: "RALT",
    MetaLeft: "LGUI",
    MetaRight: "RGUI",
    Semicolon: "SEMI",
    Quote: "SQT",
    Comma: "COMMA",
    Period: "DOT",
    Slash: "FSLH",
    Minus: "MINUS",
    Equal: "EQUAL",
    BracketLeft: "LBKT",
    BracketRight: "RBKT",
    Backslash: "BSLH",
    Backquote: "GRAVE",
    ArrowLeft: "LEFT",
    ArrowRight: "RIGHT",
    ArrowUp: "UP",
    ArrowDown: "DOWN",
  };
  return map[code] ?? null;
}
