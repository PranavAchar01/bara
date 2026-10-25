// A finished build, boiled down to what a 2D replay needs: the boards and their footprints, the
// case and its cutouts, the parts it picked and how its checks ended. Made from the build's
// recorded event stream (GET /v1/library/<id>), so the landing replay and the gallery previews
// draw real builds, never invented geometry. No imports: node runs this file directly to
// regenerate landingBuilds.json.

export interface ReplayFootprint {
  ref: string;
  label: string;
  role: string;
  /** Centre in build millimetres (board offset applied). */
  c: [number, number];
  s: [number, number];
  rot: number;
}

export interface ReplayBoard {
  outline: [number, number][];
  fp: ReplayFootprint[];
}

export interface ReplayCut {
  f: string;
  c: [number, number];
  s: [number, number];
  shape: string;
}

export interface ReplayCase {
  size: [number, number, number];
  at: [number, number];
  color: string;
  wall: number;
  cut: ReplayCut[];
}

export interface ReplayBuild {
  id: string;
  prompt: string;
  name: string;
  stages: string[];
  boards: ReplayBoard[];
  cases: ReplayCase[];
  picks: { name: string; of: number | null }[];
  /** Checks that ended passing. */
  checks: number;
  /** Checks that ended failing at error or critical severity: a build with any is not finished. */
  failed: number;
  parts: number;
}

interface Env {
  type: string;
  payload: unknown;
}

type Obj = Record<string, unknown>;
const r1 = (v: unknown) => Math.round(Number(v ?? 0) * 10) / 10;
const pt = (p: unknown, dx = 0, dy = 0): [number, number] => {
  const a = p as number[];
  return [r1(a[0] + dx), r1(a[1] + dy)];
};

/** Last result per check: the repair rounds re-run checks, and only the final word counts. */
export function finalChecks(events: Env[]): { passed: number; failed: number } {
  const last = new Map<string, Obj>();
  for (const e of events) {
    if (e.type !== "check.result") continue;
    for (const c of ((e.payload as Obj).results as Obj[]) ?? []) last.set(String(c.check_key), c);
  }
  let passed = 0;
  let failed = 0;
  for (const c of last.values()) {
    if (c.status === "pass") passed++;
    else if (c.status === "fail" && (c.severity === "error" || c.severity === "critical")) failed++;
  }
  return { passed, failed };
}

/** Distils one build's recorded events. Later board and case updates replace earlier ones. */
export function distillEvents(id: string, prompt: string, name: string, events: Env[]): ReplayBuild {
  const boards = new Map<string, Obj>();
  const cases = new Map<string, Obj>();
  const byPart = new Map<string, string>();
  const decisions: Obj[] = [];
  const stages: string[] = [];
  const instances = new Set<string>();
  for (const e of events) {
    const p = e.payload as Obj;
    if (e.type === "board.updated") {
      const b = p.board as Obj;
      boards.set(String(b.board_id), b);
    } else if (e.type === "enclosure.updated") {
      const x = p.enclosure as Obj;
      cases.set(String(x.enclosure_id), x);
    } else if (e.type === "part.added") {
      const part = p.part as Obj;
      instances.add(String(part.instance_id));
      const card = part.card as Obj;
      if (!byPart.has(String(part.part_id))) byPart.set(String(part.part_id), String(card.display_name));
    } else if (e.type === "decision.made") decisions.push(p.decision as Obj);
    else if (e.type === "stage.started") {
      const l = p.label;
      if (typeof l === "string" && !stages.includes(l)) stages.push(l);
    }
  }
  const outBoards: ReplayBoard[] = [...boards.values()].map((b) => {
    const at = (b.position_mm as number[]) ?? [0, 0];
    return {
      outline: ((b.outline_mm as unknown[]) ?? []).map((q) => pt(q, at[0], at[1])),
      fp: ((b.footprints as Obj[]) ?? []).map((f) => ({
        ref: String(f.ref),
        label: String(f.label ?? "").slice(0, 48),
        role: String(f.role ?? "part"),
        c: pt(f.center_mm, at[0], at[1]),
        s: pt(f.size_mm),
        rot: r1(f.rot_deg),
      })),
    };
  });
  const outCases: ReplayCase[] = [...cases.values()].map((x) => {
    const size = (x.outer_size_mm as number[]) ?? [0, 0, 0];
    const at = (x.position_mm as number[]) ?? [0, 0];
    const color = ((x.color as Obj | null)?.hex as string | undefined) ?? "#E6DCCB";
    return {
      size: [r1(size[0]), r1(size[1]), r1(size[2])],
      at: [r1(at[0]), r1(at[1])],
      color,
      wall: Number((x.params as Obj | undefined)?.wall_mm ?? 3),
      cut: ((x.cutouts as Obj[]) ?? [])
        .filter((c) => c.face === "pos_z")
        .map((c) => ({ f: String(c.feature), c: pt(c.center_mm), s: pt(c.size_mm), shape: String(c.shape) })),
    };
  });
  const picks = decisions
    .map((d) => ({ name: byPart.get(String(d.chosen_part_id)) ?? "", of: typeof d.survivors === "number" ? d.survivors : null }))
    .filter((p) => p.name);
  const { passed, failed } = finalChecks(events);
  return { id, prompt, name, stages, boards: outBoards, cases: outCases, picks, checks: passed, failed, parts: instances.size };
}
