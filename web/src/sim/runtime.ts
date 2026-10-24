// The simulated firmware: what the device does with a press. A device with a keymap types into a
// terminal; one with a display and direction inputs plays a game; any other keeps an event log.
// Pure state and functions, driven by the viewport (presses from the mouse or the keyboard, ticks
// from the render loop).
import { charOf, isBackspace, isShift } from "./keymap";
import type { InputMap, SimInput, SimMode } from "./inputMap";
import { action, isDir, newSnake, restart, steer, tickSnake, type SnakeGame } from "./snake";

export interface Terminal {
  text: string;
}

export const TERMINAL_MAX = 4000;

/** One key press into the terminal: a character, a newline, or a backspace. */
export function typeInto(term: Terminal, code: string, shift: boolean): void {
  if (isBackspace(code)) {
    term.text = term.text.slice(0, -1);
    return;
  }
  const ch = charOf(code, shift);
  if (ch === null) return;
  term.text = (term.text + (ch === "\t" ? "  " : ch)).slice(-TERMINAL_MAX);
}

export interface Runtime {
  mode: SimMode;
  terminal: Terminal;
  game: SnakeGame;
  /** Newest last. */
  events: string[];
  held: Set<string>;
  /** Bumped on every state change, so a view knows when to redraw. */
  version: number;
}

export const EVENT_LOG_MAX = 12;

/** Cells of the game board for a screen of this width over height. */
export function gridFor(aspect: number): { cols: number; rows: number } {
  const rows = 15;
  return { cols: Math.max(8, Math.round(rows * aspect)), rows };
}

export function createRuntime(map: InputMap, aspect = 4 / 3, rng: () => number = Math.random): Runtime {
  const { cols, rows } = gridFor(aspect);
  return { mode: map.mode, terminal: { text: "" }, game: newSnake(cols, rows, rng), events: [], held: new Set(), version: 0 };
}

function shifted(rt: Runtime, inputs: SimInput[]): boolean {
  for (const i of inputs) if (rt.held.has(i.id) && i.code && isShift(i.code)) return true;
  return false;
}

export function press(rt: Runtime, input: SimInput, all: SimInput[]): void {
  if (rt.held.has(input.id)) return;
  rt.held.add(input.id);
  rt.events.push(input.name);
  if (rt.events.length > EVENT_LOG_MAX) rt.events.shift();
  if (rt.mode === "typing" && input.code) typeInto(rt.terminal, input.code, shifted(rt, all));
  else if (rt.mode === "game") {
    if (isDir(input.name)) steer(rt.game, input.name);
    else if (input.name === "RESET") restart(rt.game);
    else action(rt.game);
  }
  rt.version++;
}

export function release(rt: Runtime, input: SimInput): void {
  if (rt.held.delete(input.id)) rt.version++;
}

/** Advance time; true when something visible changed. */
export function tick(rt: Runtime, dtMs: number): boolean {
  if (rt.mode !== "game") return false;
  const moved = tickSnake(rt.game, dtMs);
  if (moved) rt.version++;
  return moved;
}
