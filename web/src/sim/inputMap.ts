// The input map of a build: every key switch and tactile button instance, and the logical input
// it stands for. Derived from the build record alone: the parts and their placement, the board's
// footprints, and the firmware record (a ZMK `config/*.keymap` when the build has one).
//
// This is read from the pin map and layout, not by running the binary: the firmware is not
// compiled on this server, so the simulation reads what the generated files declare (key order,
// `&kp` codes) and names the rest from where each button sits on the control face.
import type { Board, BoardFootprint, Build, BuildPart } from "../spec/types";
import { elementPoses, rotateZ, type V3 } from "../three/layout";
import { charOf, isBackspace, isShift, keyCodes, keyLabel, parseKeymap } from "./keymap";

export type InputRole = "key" | "dpad" | "action" | "system";

export interface SimInput {
  /** Stable id: the part instance and the element's position in it. */
  id: string;
  /** Hover and event-strip name: "Q", "UP", "A". */
  name: string;
  /** ZMK key code when the firmware names one. */
  code: string | null;
  role: InputRole;
  instanceId: string;
  /** Element index inside the part instance (its position in the instanced mesh). */
  index: number;
  /** Shared by every mesh of this input (switch and keycap press together). */
  pressKey: string;
  /** World position in mm, before any explode. */
  pos: V3;
}

export type SimMode = "typing" | "game" | "pad";

export interface InputMap {
  mode: SimMode;
  inputs: SimInput[];
  /** Where the names came from. */
  source: "keymap" | "position";
  /** Instance ids of the build's display parts. */
  displays: string[];
}

function fn(p: BuildPart): string {
  return p.card.primary_function ?? "";
}

export function isKeyPart(p: BuildPart): boolean {
  return fn(p) === "input.key";
}

export function isButtonPart(p: BuildPart): boolean {
  return fn(p) === "input.button";
}

/** The key under a layout element or a single instance's element: one string for switch and cap alike. */
export function pressKeyOf(part: Pick<BuildPart, "instance_id" | "placement">, poseIndex: number, element: number): string {
  const layout = part.placement.mode === "layout" ? part.placement.layout_id : null;
  return layout ? `${layout}:${poseIndex}` : `${part.instance_id}:${element}`;
}

interface Raw {
  part: BuildPart;
  element: number;
  poseIndex: number;
  pos: V3;
}

const COINCIDE_MM = 0.5;

function spread(points: V3[]): number {
  let m = 0;
  for (const a of points) for (const b of points) m = Math.max(m, Math.hypot(a[0] - b[0], a[1] - b[1]));
  return m;
}

function footprintWorld(board: Board, fp: BoardFootprint, z: number): V3 | null {
  if (!fp.center_mm) return null;
  const rot = rotateZ([fp.center_mm[0], fp.center_mm[1], 0], board.rotation_deg?.[2] ?? 0);
  const p = board.position_mm ?? [0, 0, 0];
  return [p[0] + rot[0], p[1] + rot[1], z];
}

function refNumber(ref: string): number {
  const m = /(\d+)$/.exec(ref);
  return m ? Number(m[1]) : 0;
}

/** Button footprints of every board, in reference order (SW1, SW2, ...). */
function buttonFootprints(build: Build): V3[] {
  const out: { n: number; at: V3 }[] = [];
  for (const board of build.boards ?? []) {
    for (const fp of board.footprints ?? []) {
      if (fp.role !== "button") continue;
      const at = footprintWorld(board, fp, 0);
      if (at) out.push({ n: refNumber(fp.ref), at });
    }
  }
  return out.sort((a, b) => a.n - b.n).map((o) => o.at);
}

/**
 * Every element of every input part with its world position. A part of several buttons that the
 * placement stacks at one point (a quantity with no layout) takes its positions from the board's
 * button footprints: the ones no other part claims by position, handed out in reference order.
 */
function collect(build: Build, parts: BuildPart[]): Raw[] {
  const layouts = build.layouts ?? [];
  const posed = parts.map((part) => {
    const layout = layouts.find((l) => l.layout_id === part.placement.layout_id);
    return { part, poses: elementPoses(part.placement, part.quantity, layout) };
  });
  let free = buttonFootprints(build);
  for (const { poses } of posed) {
    if (poses.length > 1 && spread(poses.map((p) => p.position)) < COINCIDE_MM) continue;
    for (const p of poses) free = free.filter((f) => Math.hypot(f[0] - p.position[0], f[1] - p.position[1]) > COINCIDE_MM);
  }
  const out: Raw[] = [];
  for (const { part, poses } of posed) {
    const stacked = poses.length > 1 && spread(poses.map((p) => p.position)) < COINCIDE_MM;
    poses.forEach((p, element) => {
      let pos = p.position;
      if (stacked && free.length) {
        const f = free.shift();
        if (f) pos = [f[0], f[1], p.position[2]];
      }
      out.push({ part, element, poseIndex: p.index, pos });
    });
  }
  return out;
}

/** Top row first, left to right inside a row: the order a keymap lists keys when the record gives none. */
export function orderByPosition<T extends { pos: V3 }>(items: T[], rowMm = 5): T[] {
  const byY = [...items].sort((a, b) => b.pos[1] - a.pos[1]);
  const rows: T[][] = [];
  for (const it of byY) {
    const row = rows.find((r) => Math.abs(r[0].pos[1] - it.pos[1]) <= rowMm);
    if (row) row.push(it);
    else rows.push([it]);
  }
  return rows.flatMap((r) => r.sort((a, b) => a.pos[0] - b.pos[0]));
}

export interface Plus {
  up: number;
  down: number;
  left: number;
  right: number;
}

/**
 * Four points in a plus: one above and one below on a shared vertical, one left and one right on
 * a shared horizontal, all about the same distance from the middle. Indices into `pts`. When
 * several pluses exist the leftmost wins (a handheld's D-pad sits left of its buttons).
 */
export function findPlus(pts: { x: number; y: number }[]): Plus | null {
  const n = pts.length;
  if (n < 4 || n > 40) return null;
  let best: { plus: Plus; cx: number } | null = null;
  for (let a = 0; a < n; a++)
    for (let b = a + 1; b < n; b++)
      for (let c = b + 1; c < n; c++)
        for (let d = c + 1; d < n; d++) {
          const idx = [a, b, c, d];
          const p = idx.map((i) => pts[i]);
          const up = idx[p.indexOf(p.reduce((m, q) => (q.y > m.y ? q : m)))];
          const down = idx[p.indexOf(p.reduce((m, q) => (q.y < m.y ? q : m)))];
          const left = idx[p.indexOf(p.reduce((m, q) => (q.x < m.x ? q : m)))];
          const right = idx[p.indexOf(p.reduce((m, q) => (q.x > m.x ? q : m)))];
          if (new Set([up, down, left, right]).size !== 4) continue;
          const cx = (pts[up].x + pts[down].x) / 2;
          const cy = (pts[left].y + pts[right].y) / 2;
          const arms = [pts[up], pts[down], pts[left], pts[right]].map((q) => Math.hypot(q.x - cx, q.y - cy));
          const arm = arms.reduce((s, v) => s + v, 0) / 4;
          if (arm < 3) continue;
          const tol = arm * 0.25;
          if (Math.abs(pts[up].x - pts[down].x) > tol || Math.abs(pts[left].y - pts[right].y) > tol) continue;
          if (arms.some((v) => Math.abs(v - arm) > tol)) continue;
          if (!best || cx < best.cx) best = { plus: { up, down, left, right }, cx };
        }
  return best?.plus ?? null;
}

const SYSTEM_WORDS = /\b(reset|boot|select|start|menu|power|mode)\b/gi;

/** Reset and boot style buttons are named by the part's own label, in the order the label lists them. */
function systemNames(part: BuildPart): string[] {
  const text = `${part.label ?? ""} ${part.card.display_name}`;
  return [...text.matchAll(SYSTEM_WORDS)].map((m) => m[1].toUpperCase());
}

function isSystemPart(part: BuildPart): boolean {
  return systemNames(part).length > 0;
}

interface Named {
  raw: Raw;
  name: string;
  role: InputRole;
  code?: string | null;
}

/** Names for buttons without a keymap, from where they sit on the control face (plus shape, then position). */
function nameButtons(raws: Raw[]): Named[] {
  const out: Named[] = [];
  const system = raws.filter((r) => isSystemPart(r.part));
  const rest = raws.filter((r) => !isSystemPart(r.part));
  const plus = findPlus(rest.map((r) => ({ x: r.pos[0], y: r.pos[1] })));
  const used = new Set<number>();
  if (plus) {
    const arms: [keyof Plus, string][] = [["up", "UP"], ["down", "DOWN"], ["left", "LEFT"], ["right", "RIGHT"]];
    for (const [k, name] of arms) {
      used.add(plus[k]);
      out.push({ raw: rest[plus[k]], name, role: "dpad" });
    }
  }
  const actions = orderByPosition(rest.filter((_, i) => !used.has(i)));
  const letters = ["Y", "X", "B", "A"];
  actions.forEach((raw, i) => {
    const fromEnd = actions.length - 1 - i;
    out.push({ raw, name: fromEnd < letters.length ? letters[letters.length - 1 - fromEnd] : `BTN${i + 1}`, role: "action" });
  });
  // System buttons: the words in the label, in order; then SELECT and START for what is left.
  const spare = ["SELECT", "START"];
  for (const r of system) {
    const words = systemNames(r.part);
    const sameName = system.filter((s) => s.part.instance_id === r.part.instance_id);
    const k = sameName.indexOf(r);
    const word = words[k] ?? words[words.length - 1] ?? spare.shift() ?? "BTN";
    out.push({ raw: r, name: word, role: "system" });
  }
  return out;
}

function keymapOf(build: Build): string | null {
  const file = build.firmware?.files.find((f) => /\.keymap$/.test(f.path) && f.content);
  return file?.content ?? null;
}

/** Keymap codes on key switches: record order when the counts agree, position order when they do not. */
function nameKeys(raws: Raw[], content: string): Named[] {
  const codes = keyCodes(parseKeymap(content));
  const ordered = codes.length === raws.length ? raws : orderByPosition(raws);
  return ordered.map((raw, i): Named => {
    const code = codes[i] ?? null;
    return { raw, name: code ? keyLabel(code) : `K${i + 1}`, role: "key", code };
  });
}

const TYPING_MIN_KEYS = 8;

/** The build's input map; empty inputs when it has no key or button parts. */
export function deriveInputMap(build: Build | null): InputMap {
  const empty: InputMap = { mode: "pad", inputs: [], source: "position", displays: [] };
  if (!build) return empty;
  const displays = build.parts.filter((p) => fn(p).startsWith("display.") && fn(p) !== "display.indicator_led").map((p) => p.instance_id);
  const keyRaws = collect(build, build.parts.filter(isKeyPart));
  const buttonRaws = collect(build, build.parts.filter(isButtonPart));
  if (!keyRaws.length && !buttonRaws.length) return { ...empty, displays };
  const content = keymapOf(build);
  const named: Named[] = [];
  if (keyRaws.length) {
    if (content) named.push(...nameKeys(keyRaws, content));
    else orderByPosition(keyRaws).forEach((raw, i) => named.push({ raw, name: `K${i + 1}`, role: "key", code: null }));
  }
  named.push(...nameButtons(buttonRaws));
  const inputs: SimInput[] = named.map((n) => ({
    id: `${n.raw.part.instance_id}#${n.raw.element}`,
    name: n.name,
    code: n.code ?? null,
    role: n.role,
    instanceId: n.raw.part.instance_id,
    index: n.raw.element,
    pressKey: pressKeyOf(n.raw.part, n.raw.poseIndex, n.raw.element),
    pos: n.raw.pos,
  }));
  const typing = !!content && keyRaws.length >= TYPING_MIN_KEYS;
  const mode: SimMode = typing ? "typing" : displays.length ? "game" : "pad";
  return { mode, inputs, source: content && keyRaws.length ? "keymap" : "position", displays };
}

export { charOf, isBackspace, isShift };
