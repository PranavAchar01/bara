// A small snake game for any device with a screen and direction inputs. Pure: the caller feeds
// time and presses, and draws `snake` and `food` itself.

export type Dir = "UP" | "DOWN" | "LEFT" | "RIGHT";
export type SnakeStatus = "ready" | "running" | "paused" | "over";

export interface SnakeGame {
  cols: number;
  rows: number;
  body: [number, number][];
  dir: Dir;
  queued: Dir;
  food: [number, number];
  score: number;
  best: number;
  status: SnakeStatus;
  /** Milliseconds since the last step. */
  acc: number;
  stepMs: number;
  rng: () => number;
}

const VEC: Record<Dir, [number, number]> = { UP: [0, -1], DOWN: [0, 1], LEFT: [-1, 0], RIGHT: [1, 0] };
const OPPOSITE: Record<Dir, Dir> = { UP: "DOWN", DOWN: "UP", LEFT: "RIGHT", RIGHT: "LEFT" };

export function isDir(name: string): name is Dir {
  return name === "UP" || name === "DOWN" || name === "LEFT" || name === "RIGHT";
}

/** Small deterministic generator, so a test can replay a game. */
export function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function placeFood(g: SnakeGame): [number, number] {
  const free: [number, number][] = [];
  for (let y = 0; y < g.rows; y++) for (let x = 0; x < g.cols; x++) if (!g.body.some((b) => b[0] === x && b[1] === y)) free.push([x, y]);
  return free.length ? free[Math.floor(g.rng() * free.length)] : [0, 0];
}

export function newSnake(cols: number, rows: number, rng: () => number = Math.random, best = 0): SnakeGame {
  const y = Math.floor(rows / 2);
  const x = Math.max(2, Math.floor(cols / 3));
  const g: SnakeGame = {
    cols,
    rows,
    body: [[x, y], [x - 1, y], [x - 2, y]],
    dir: "RIGHT",
    queued: "RIGHT",
    food: [0, 0],
    score: 0,
    best,
    status: "ready",
    acc: 0,
    stepMs: 140,
    rng,
  };
  g.food = placeFood(g);
  return g;
}

/** A direction press: steers (never straight back into itself) and starts a waiting game. */
export function steer(g: SnakeGame, dir: Dir): void {
  if (g.status === "ready" || g.status === "over") {
    if (g.status === "over") restart(g);
    g.status = "running";
  }
  if (g.status === "paused") g.status = "running";
  if (dir !== OPPOSITE[g.dir]) g.queued = dir;
}

/** Any other button: start, pause or resume, restart after a game over. */
export function action(g: SnakeGame): void {
  if (g.status === "ready") g.status = "running";
  else if (g.status === "running") g.status = "paused";
  else if (g.status === "paused") g.status = "running";
  else {
    restart(g);
    g.status = "running";
  }
}

export function restart(g: SnakeGame): void {
  const fresh = newSnake(g.cols, g.rows, g.rng, g.best);
  Object.assign(g, fresh, { status: "ready" as SnakeStatus });
}

function step(g: SnakeGame): void {
  g.dir = g.queued;
  const [dx, dy] = VEC[g.dir];
  const head = g.body[0];
  const next: [number, number] = [head[0] + dx, head[1] + dy];
  const eats = next[0] === g.food[0] && next[1] === g.food[1];
  const tail = eats ? g.body : g.body.slice(0, -1);
  const hit = next[0] < 0 || next[1] < 0 || next[0] >= g.cols || next[1] >= g.rows || tail.some((b) => b[0] === next[0] && b[1] === next[1]);
  if (hit) {
    g.status = "over";
    g.best = Math.max(g.best, g.score);
    return;
  }
  g.body = [next, ...tail];
  if (eats) {
    g.score += 1;
    g.stepMs = Math.max(70, g.stepMs - 3);
    g.food = placeFood(g);
  }
}

/** Advance by `dtMs`; true when the picture changed. */
export function tickSnake(g: SnakeGame, dtMs: number): boolean {
  if (g.status !== "running") return false;
  g.acc += Math.min(dtMs, 250);
  let moved = false;
  while (g.acc >= g.stepMs && g.status === "running") {
    g.acc -= g.stepMs;
    step(g);
    moved = true;
  }
  return moved;
}
