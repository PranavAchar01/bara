// ZMK keymap reading: the `&kp X` bindings of a `config/*.keymap` file, in key order, and the
// characters those key codes type. Pure; the firmware is read as text, never run.

export interface Binding {
  /** Behavior name without the ampersand: "kp", "mo", "trans". */
  behavior: string;
  /** First parameter, e.g. the key code of a `&kp`; null for a behavior with none. */
  param: string | null;
}

/** Bindings of the first `bindings = < ... >;` block (the base layer), in file order. */
export function parseKeymap(content: string): Binding[] {
  const block = /bindings\s*=\s*<([\s\S]*?)>\s*;/.exec(content);
  if (!block) return [];
  const body = block[1].replace(/\/\/.*$/gm, "").replace(/\/\*[\s\S]*?\*\//g, "");
  const out: Binding[] = [];
  for (const chunk of body.split("&").slice(1)) {
    const tokens = chunk.trim().split(/\s+/).filter(Boolean);
    if (!tokens.length) continue;
    out.push({ behavior: tokens[0], param: tokens[1] ?? null });
  }
  return out;
}

/** The key code of each binding that is a plain `&kp`; null for every other behavior. */
export function keyCodes(bindings: Binding[]): (string | null)[] {
  return bindings.map((b) => (b.behavior === "kp" ? b.param : null));
}

const PLAIN: Record<string, [string, string]> = {
  SPACE: [" ", " "],
  SEMI: [";", ":"],
  SEMICOLON: [";", ":"],
  COMMA: [",", "<"],
  DOT: [".", ">"],
  PERIOD: [".", ">"],
  FSLH: ["/", "?"],
  SLASH: ["/", "?"],
  BSLH: ["\\", "|"],
  BACKSLASH: ["\\", "|"],
  MINUS: ["-", "_"],
  EQUAL: ["=", "+"],
  LBKT: ["[", "{"],
  RBKT: ["]", "}"],
  SQT: ["'", '"'],
  APOS: ["'", '"'],
  GRAVE: ["`", "~"],
  EXCL: ["!", "!"],
  EXCLAMATION: ["!", "!"],
  AT: ["@", "@"],
  HASH: ["#", "#"],
  POUND: ["#", "#"],
  DLLR: ["$", "$"],
  DOLLAR: ["$", "$"],
  PRCNT: ["%", "%"],
  PERCENT: ["%", "%"],
  CARET: ["^", "^"],
  AMPS: ["&", "&"],
  AMPERSAND: ["&", "&"],
  STAR: ["*", "*"],
  ASTRK: ["*", "*"],
  LPAR: ["(", "("],
  RPAR: [")", ")"],
  UNDER: ["_", "_"],
  PLUS: ["+", "+"],
  COLON: [":", ":"],
  PIPE: ["|", "|"],
  TILDE: ["~", "~"],
  QMARK: ["?", "?"],
  LT: ["<", "<"],
  GT: [">", ">"],
  DQT: ['"', '"'],
  LBRC: ["{", "{"],
  RBRC: ["}", "}"],
};

const SHIFT_DIGITS = ")!@#$%^&*(";

/** What a key code types, or null when it types nothing (modifiers, arrows, layer keys). */
export function charOf(code: string, shift: boolean): string | null {
  if (/^[A-Z]$/.test(code)) return shift ? code : code.toLowerCase();
  const digit = /^(?:N|NUMBER_)([0-9])$/.exec(code);
  if (digit) return shift ? SHIFT_DIGITS[Number(digit[1])] : digit[1];
  const plain = PLAIN[code];
  if (plain) return plain[shift ? 1 : 0];
  if (code === "RET" || code === "RETURN" || code === "ENTER") return "\n";
  if (code === "TAB") return "\t";
  return null;
}

export function isBackspace(code: string): boolean {
  return code === "BSPC" || code === "BACKSPACE";
}

export function isShift(code: string): boolean {
  return code === "LSHFT" || code === "RSHFT" || code === "LSHIFT" || code === "RSHIFT";
}

/** Short name shown on hover and in the event strip: the character, or the code as ZMK spells it. */
export function keyLabel(code: string): string {
  const digit = /^(?:N|NUMBER_)([0-9])$/.exec(code);
  if (digit) return digit[1];
  const plain = PLAIN[code];
  if (plain && code !== "SPACE") return plain[0];
  return code;
}
