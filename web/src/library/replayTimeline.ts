// The landing replay as a pure function of time: given a distilled build and t seconds into its
// run, where every part is, how far the board, the traces and the case have got, what the agent
// is pointing at and what it says. The component (BuildScene) only draws this.
import type { ReplayBuild, ReplayFootprint } from "./replayData";

/** Phase windows, in seconds from the start of one device's run. */
export const T = {
  type: [0.2, 2.0],
  parts: [2.5, 6.6],
  board: [6.0, 7.2],
  drop: [6.9, 8.4],
  route: [8.4, 10.8],
  walls: [10.8, 12.4],
  lid: [12.1, 13.5],
  done: [13.6, 15.8],
  out: [15.8, 16.5],
} as const;
export const RUN_S = T.out[1];

const ROLE_ORDER = ["mcu", "screen", "encoder", "joystick", "switch", "button", "speaker", "sd_card", "connector", "battery_connector", "charger", "regulator"];

/** How tall each kind of part stands, in mm, for the drawing. */
export function roleHeight(role: string): number {
  return ({ switch: 6, encoder: 9, joystick: 10, screen: 3, mcu: 2.2, button: 2.5, speaker: 3, battery_connector: 4, haptic: 3, potentiometer: 6 } as Record<string, number>)[role] ?? 1.6;
}

export const clamp01 = (v: number) => (v < 0 ? 0 : v > 1 ? 1 : v);
const span = (t: number, w: readonly [number, number]) => clamp01((t - w[0]) / (w[1] - w[0]));
export const easeOut = (v: number) => 1 - (1 - v) ** 3;
export const easeInOut = (v: number) => (v < 0.5 ? 4 * v * v * v : 1 - (-2 * v + 2) ** 3 / 2);

export interface PlacedFp extends ReplayFootprint {
  /** 0..1: popped into view (floating above the board). */
  appear: number;
  /** 0..1: dropped from its floating height onto the board. */
  land: number;
  /** When it appears, in seconds. */
  at: number;
}

export interface Trace {
  pts: [number, number][];
  /** 0..1 drawn. */
  drawn: number;
}

export interface Frame {
  typed: number;
  stage: string;
  fps: PlacedFp[];
  board: number;
  traces: Trace[];
  walls: number;
  lid: number;
  done: number;
  /** Whole-scene opacity: fades out at the end of the run. */
  alpha: number;
  /** Where the cursor points, in build mm (z in mm above the desk), or "prompt" for the prompt pill. */
  cursor: { x: number; y: number; z: number } | "prompt";
  /** True for a short moment while the cursor presses. */
  pressing: boolean;
  say: string | null;
  activity: "read" | "pick" | "arrange" | "route" | "sculpt" | "admire";
}

/** Drops the manufacturer in brackets ("RKJXV1224005 (ALPSALPINE(...))") and trailing package notes. */
export function cleanPartName(s: string): string {
  return s.replace(/\s*\((?:[^()]|\([^()]*\))*\)\s*$/, "").trim() || s;
}

/** Footprints in the order the agent picks them: the brain first, then what you touch, then the rest. */
export function pickOrder(b: ReplayBuild): ReplayFootprint[] {
  const all = b.boards.flatMap((x) => x.fp);
  const rank = (r: string) => {
    const i = ROLE_ORDER.indexOf(r);
    return i < 0 ? ROLE_ORDER.length : i;
  };
  return [...all].sort((a, b2) => rank(a.role) - rank(b2.role) || a.c[1] - b2.c[1] || a.c[0] - b2.c[0]);
}

/** The ones the cursor clicks on: the first of each kind of part, at most six. */
function clickTargets(order: ReplayFootprint[]): number[] {
  const seen = new Set<string>();
  const out: number[] = [];
  order.forEach((f, i) => {
    const key = cleanPartName(f.label) || f.role;
    if (seen.has(key) || out.length >= 6 || f.role === "passive" || f.role === "diode") return;
    seen.add(key);
    out.push(i);
  });
  return out;
}

/** 45-degree PCB-style route from a to b: straight, then a chamfer onto the target. */
function route(a: [number, number], b: [number, number]): [number, number][] {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const d = Math.min(Math.abs(dx), Math.abs(dy));
  const bend: [number, number] = [b[0] - Math.sign(dx) * d, a[1]];
  return [a, bend, b];
}

export interface Prepared {
  build: ReplayBuild;
  order: ReplayFootprint[];
  clicks: number[];
  traces: [number, number][][];
  /** Extent of everything in mm: [minX, minY, maxX, maxY]. */
  box: [number, number, number, number];
  caseH: number;
}

export function prepare(build: ReplayBuild): Prepared {
  const order = pickOrder(build);
  const clicks = clickTargets(order);
  const hub = order.find((f) => f.role === "mcu") ?? order[0];
  const traces = hub
    ? order
        .filter((f) => f !== hub && f.role !== "passive")
        .slice(0, 28)
        .map((f) => route(hub.c, f.c))
    : [];
  const xs: number[] = [];
  const ys: number[] = [];
  for (const c of build.cases) {
    xs.push(c.at[0] - c.size[0] / 2, c.at[0] + c.size[0] / 2);
    ys.push(c.at[1] - c.size[1] / 2, c.at[1] + c.size[1] / 2);
  }
  for (const b of build.boards)
    for (const q of b.outline) {
      xs.push(q[0]);
      ys.push(q[1]);
    }
  const box: [number, number, number, number] = xs.length ? [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)] : [-50, -50, 50, 50];
  // a tall case (63 mm controller) would read as a tower in this view: cap it to a slab
  const tallest = Math.max(0, ...build.cases.map((c) => c.size[2]));
  const caseH = Math.min(tallest || 12, 0.16 * Math.min(box[2] - box[0], box[3] - box[1]) + 6);
  return { build, order, clicks, traces, box, caseH };
}

function stageLabel(b: ReplayBuild, re: RegExp, fallback: string): string {
  return b.stages.find((s) => re.test(s)) ?? fallback;
}

/** The scene at t seconds into one device's run. */
export function frameAt(p: Prepared, t: number): Frame {
  const { build, order, clicks } = p;
  const n = order.length;
  const pw = T.parts[1] - T.parts[0];
  const fps: PlacedFp[] = order.map((f, i) => {
    const at = T.parts[0] + (n > 1 ? (i / (n - 1)) * pw * 0.92 : 0);
    const landAt = T.drop[0] + (n > 1 ? (i / (n - 1)) * 0.7 : 0);
    return { ...f, at, appear: easeOut(clamp01((t - at) / 0.35)), land: easeInOut(clamp01((t - landAt) / 0.6)) };
  });
  const routeP = span(t, T.route);
  const traces = p.traces.map((pts, i) => {
    const k = p.traces.length > 1 ? i / (p.traces.length - 1) : 0;
    const start = k * 0.6;
    return { pts, drawn: easeInOut(clamp01((routeP - start) / 0.4)) };
  });
  const typedChars = Math.round(span(t, T.type) * build.prompt.length);
  const [x0, y0, x1, y1] = p.box;
  const cx = (x0 + x1) / 2;
  const floatZ = 26;
  let cursor: Frame["cursor"] = "prompt";
  let pressing = false;
  let say: string | null = null;
  let stage = stageLabel(build, /understand/i, "Understanding the request");
  let activity: Frame["activity"] = "read";

  if (t >= T.type[1] + 0.3 && t < T.board[0]) {
    stage = stageLabel(build, /choos|pick/i, "Choosing parts");
    activity = "pick";
    // the cursor visits each click target as it appears, pressing on arrival
    let idx = clicks.findIndex((ci, k) => t < (fps[clicks[k + 1]]?.at ?? T.board[0]) && t >= fps[ci].at - 0.45);
    if (idx < 0) idx = 0;
    const f = fps[clicks[idx]] ?? fps[0];
    if (f) {
      cursor = { x: f.c[0], y: f.c[1], z: floatZ + roleHeight(f.role) };
      pressing = t >= f.at && t < f.at + 0.18;
      const same = order.filter((o) => cleanPartName(o.label) === cleanPartName(f.label)).length;
      const pick = build.picks.find((x) => cleanPartName(x.name) === cleanPartName(f.label));
      const name = cleanPartName(f.label);
      say = t >= f.at - 0.1 ? (same > 1 ? `${same} × ${name}` : pick?.of && pick.of > 1 ? `${name}, best of ${pick.of}` : name) : null;
    }
  } else if (t >= T.board[0] && t < T.route[0]) {
    stage = stageLabel(build, /plac/i, "Placing parts on the board");
    activity = "arrange";
    const ob = build.boards[0]?.outline ?? [];
    const corner = ob.reduce<[number, number]>((m, q) => (q[0] + q[1] < m[0] + m[1] ? q : m), ob[0] ?? [x0, y0]);
    cursor = { x: corner[0], y: corner[1], z: 2 };
    pressing = t >= T.board[0] + 0.5 && t < T.board[0] + 0.7;
    const bw = Math.round(x1 - x0);
    const bh = Math.round(y1 - y0);
    say = `Board ${bw} × ${bh} mm`;
  } else if (t >= T.route[0] && t < T.walls[0]) {
    stage = stageLabel(build, /rout/i, "Routing the board");
    activity = "route";
    const live = traces.find((tr) => tr.drawn > 0 && tr.drawn < 1) ?? traces.at(-1);
    if (live) {
      const end = live.pts[live.pts.length - 1];
      cursor = { x: end[0], y: end[1], z: 3 };
    }
    say = `Routing ${n} footprints`;
  } else if (t >= T.walls[0] && t < T.done[0]) {
    stage = stageLabel(build, /case|enclos/i, "Shaping the case");
    activity = "sculpt";
    const c = build.cases[0];
    const lift = p.caseH * easeOut(span(t, T.walls));
    cursor = c ? { x: c.at[0] + c.size[0] / 2 - 4, y: c.at[1] - c.size[1] / 2 + 4, z: lift } : { x: cx, y: y0, z: lift };
    pressing = t >= T.lid[0] && t < T.lid[0] + 0.2;
    if (c) say = `Case ${Math.round(c.size[0])} × ${Math.round(c.size[1])} mm, ${c.wall} mm walls`;
  } else if (t >= T.done[0]) {
    stage = `${build.checks} checks passed`;
    activity = "admire";
    cursor = { x: x1 - 6, y: y0 + 8, z: p.caseH + 4 };
    say = `${build.checks} checks passed`;
  }

  return {
    typed: typedChars,
    stage,
    fps,
    board: easeOut(span(t, T.board)),
    traces,
    walls: easeOut(span(t, T.walls)),
    lid: easeInOut(span(t, T.lid)),
    done: span(t, T.done),
    alpha: 1 - span(t, T.out),
    cursor,
    pressing,
    say,
    activity,
  };
}
