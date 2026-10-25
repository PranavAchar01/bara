// The landing's animation: a small mock of the app (tab bar, sidebar, canvas, notifications)
// replaying real builds from the engine's library from scratch. The prompt is typed in the
// sidebar, parts pop in, the board slides under them, traces route, the clear case rises around
// it and the lid closes, while Bara works the canvas as a cursor and notifications pop and fade.
// It is a documented replay (library/landingBuilds.json, distilled from stored build events), not
// the live UI. Under reduced motion it is one still: the first device, finished.
import { useEffect, useMemo, useRef, useState } from "react";
import type { ReplayBuild } from "../library/replayData";
import { clamp01, easeOut, frameAt, prepare, roleHeight, RUN_S, T, type Frame, type Prepared } from "../library/replayTimeline";
import { reducedMotion } from "../bot/spring";
import { SceneAgent, type AgentAim } from "./LandingAgent";
import landing from "../library/landingBuilds.json";

// only replays whose checks all held (the macropad's board check failed, so it sits out)
const BUILDS = (landing as ReplayBuild[]).filter((b) => b.failed === 0);

/** Oblique view: depth (y) squashed, height (z) lifts toward the top of the screen. */
const K = 0.56;
const Z = 0.82;
const FLOAT_Z = 26;
const FLOOR = 2;
const BOARD_T = 1.6;

type V2 = [number, number];
const P = (x: number, y: number, z: number): V2 => [x, -y * K - z * Z];
const pts = (a: V2[]) => a.map((p) => `${p[0].toFixed(2)},${p[1].toFixed(2)}`).join(" ");

function shade(hex: string, f: number): string {
  const h = hex.replace("#", "");
  const n = parseInt(h.length === 3 ? h.replace(/./g, "$&$&") : h.slice(0, 6), 16);
  const c = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => Math.max(0, Math.min(255, Math.round(f >= 1 ? v + (255 - v) * (f - 1) : v * f))));
  return `rgb(${c[0]} ${c[1]} ${c[2]})`;
}

function rectCorners(cx: number, cy: number, w: number, h: number, rotDeg: number): V2[] {
  const r = (rotDeg * Math.PI) / 180;
  const c = Math.cos(r);
  const s = Math.sin(r);
  return [
    [-w / 2, -h / 2],
    [w / 2, -h / 2],
    [w / 2, h / 2],
    [-w / 2, h / 2],
  ].map(([x, y]) => [cx + x * c - y * s, cy + x * s + y * c]);
}

function roundedRect(cx: number, cy: number, w: number, h: number, rad: number): V2[] {
  const out: V2[] = [];
  const r = Math.min(rad, w / 2, h / 2);
  const cs: [number, number, number][] = [
    [cx + w / 2 - r, cy - h / 2 + r, -90],
    [cx + w / 2 - r, cy + h / 2 - r, 0],
    [cx - w / 2 + r, cy + h / 2 - r, 90],
    [cx - w / 2 + r, cy - h / 2 + r, 180],
  ];
  for (const [x, y, a0] of cs)
    for (let i = 0; i <= 6; i++) {
      const a = ((a0 + (i * 90) / 6) * Math.PI) / 180;
      out.push([x + r * Math.cos(a), y + r * Math.sin(a)]);
    }
  return out;
}

/** Signed area > 0 means counter-clockwise in build coordinates (y up). */
function ccw(poly: V2[]): boolean {
  let a = 0;
  for (let i = 0; i < poly.length; i++) {
    const p = poly[i];
    const q = poly[(i + 1) % poly.length];
    a += p[0] * q[1] - q[0] * p[1];
  }
  return a > 0;
}

/** The side faces of an extruded footprint; front (facing the viewer, -y) or back ones. */
function sides(poly: V2[], z0: number, z1: number, front: boolean): V2[][] {
  const out: V2[][] = [];
  const dir = ccw(poly) ? 1 : -1;
  for (let i = 0; i < poly.length; i++) {
    const a = poly[i];
    const b = poly[(i + 1) % poly.length];
    // outward normal of edge a->b for a ccw polygon is (dy, -dx)
    const ny = -(b[0] - a[0]) * dir;
    if (front ? ny < -1e-6 : ny > 1e-6) out.push([P(a[0], a[1], z0), P(b[0], b[1], z0), P(b[0], b[1], z1), P(a[0], a[1], z1)]);
  }
  return out;
}

function Prism(props: { poly: V2[]; z0: number; z1: number; fill: string; stroke?: string; opacity?: number }) {
  const { poly, z0, z1, fill } = props;
  const top = poly.map((p) => P(p[0], p[1], z1));
  return (
    <g opacity={props.opacity}>
      {z1 - z0 > 0.05 && sides(poly, z0, z1, true).map((q, i) => <polygon key={i} points={pts(q)} fill={shade(fill, 0.78)} stroke={props.stroke} strokeWidth={0.25} />)}
      <polygon points={pts(top)} fill={fill} stroke={props.stroke ?? shade(fill, 0.6)} strokeWidth={0.3} strokeLinejoin="round" />
    </g>
  );
}

const ROLE_FILL: Record<string, string> = {
  mcu: "#2e2e2e",
  screen: "#3a3f45",
  switch: "#d6d6d6",
  encoder: "#9aa0a6",
  joystick: "#4a4a4a",
  button: "#f2f2f0",
  speaker: "#6b6b6b",
  battery_connector: "#f4e7c5",
};

/** One frame of one device, drawn. Pure: the same frame always draws the same picture. */
export function SceneDrawing(props: { prep: Prepared; frame: Frame; className?: string }) {
  const { prep, frame } = props;
  const { build, box, caseH } = prep;
  const [x0, y0, x1, y1] = box;
  const vb = viewBox(prep);
  const boardZ = FLOOR + (1 - frame.board) * -18;
  const boardTop = boardZ + BOARD_T;
  const wallH = caseH * frame.walls;
  const lidZ = caseH + (1 - frame.lid) * 34;
  const fps = [...frame.fps].sort((a, b) => b.c[1] - a.c[1]);
  const keyRoles = new Set(["switch", "encoder", "joystick"]);
  return (
    <svg className={props.className} viewBox={vb.join(" ")} preserveAspectRatio="xMidYMid meet" aria-hidden>
      <g opacity={frame.alpha}>
        {/* desk shadow under where the device will be */}
        <ellipse cx={(x0 + x1) / 2} cy={-((y0 + y1) / 2) * K + 2} rx={(x1 - x0) * 0.58} ry={(y1 - y0) * K * 0.6} fill="rgb(0 0 0 / 0.05)" />
        {/* the case: floor and far walls behind everything */}
        {build.cases.map((c, i) => {
          const poly = roundedRect(c.at[0], c.at[1], c.size[0], c.size[1], 9);
          return (
            <g key={`cb${i}`} opacity={clamp01(frame.walls * 3)}>
              <polygon points={pts(poly.map((p) => P(p[0], p[1], 0)))} fill={shade(c.color, 0.86)} fillOpacity={0.5} />
              {sides(poly, 0, wallH, false).map((q, k) => (
                <polygon key={k} points={pts(q)} fill={shade(c.color, 0.7)} fillOpacity={0.35} />
              ))}
            </g>
          );
        })}
        {/* boards */}
        {build.boards.map((b, i) => (
          <Prism key={`b${i}`} poly={b.outline} z0={boardZ} z1={boardTop} fill="#cfe2cf" stroke="#9fbf9f" opacity={frame.board} />
        ))}
        {/* traces on the board's top copper */}
        <g fill="none" stroke="#c4874a" strokeWidth={0.9} strokeLinecap="round" strokeLinejoin="round" opacity={frame.board}>
          {frame.traces.map((tr, i) =>
            tr.drawn > 0 ? <polyline key={i} points={pts(tr.pts.map((p) => P(p[0], p[1], boardTop + 0.05)))} pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - tr.drawn} /> : null,
          )}
        </g>
        {/* parts: float in, then drop onto the board */}
        {fps.map((f, n) => {
          if (f.appear <= 0) return null;
          const h = roleHeight(f.role);
          const zb = boardTop + (1 - f.land) * FLOAT_Z;
          const sc = 0.55 + 0.45 * f.appear;
          const poly = rectCorners(f.c[0], f.c[1], Math.max(1.2, f.s[0] * sc), Math.max(1.2, f.s[1] * sc), f.rot);
          return <Prism key={`${n}${f.ref}`} poly={poly} z0={zb} z1={zb + h} fill={ROLE_FILL[f.role] ?? "#e4e4e4"} opacity={f.appear} />;
        })}
        {/* the case's near walls rise in front of the parts; the rim marks the top */}
        {build.cases.map((c, i) => {
          const poly = roundedRect(c.at[0], c.at[1], c.size[0], c.size[1], 9);
          return (
            <g key={`cf${i}`} opacity={clamp01(frame.walls * 3)}>
              {sides(poly, 0, wallH, true).map((q, k) => (
                <polygon key={k} points={pts(q)} fill={shade(c.color, 0.8)} fillOpacity={0.28} stroke={shade(c.color, 0.6)} strokeWidth={0.3} />
              ))}
              <polygon points={pts(poly.map((p) => P(p[0], p[1], wallH)))} fill="none" stroke={shade(c.color, 0.62)} strokeWidth={0.6} />
            </g>
          );
        })}
        {/* the lid closes with its cutouts; keys and knobs poke through */}
        {frame.lid > 0 &&
          build.cases.map((c, i) => {
            const poly = roundedRect(c.at[0], c.at[1], c.size[0], c.size[1], 9);
            const a = easeOut(frame.lid);
            return (
              <g key={`l${i}`} opacity={a}>
                <polygon points={pts(poly.map((p) => P(p[0], p[1], lidZ)))} fill={shade(c.color, 1.06)} fillOpacity={0.3} stroke={shade(c.color, 0.55)} strokeWidth={0.45} />
                {c.cut.map((k, j) => {
                  const z = lidZ + 0.05;
                  const fill = k.f.includes("screen") ? "rgb(38 42 46 / 0.85)" : "none";
                  if (k.shape === "circle" || k.f === "stick" || k.f === "encoder") {
                    const [cx, cy] = P(k.c[0], k.c[1], z);
                    return <ellipse key={j} cx={cx} cy={cy} rx={k.s[0] / 2} ry={(k.s[1] / 2) * K} fill={fill} />;
                  }
                  return <polygon key={j} points={pts(roundedRect(k.c[0], k.c[1], k.s[0], k.s[1], Math.min(k.s[0], k.s[1]) * 0.18).map((p) => P(p[0], p[1], z)))} fill={fill} />;
                })}
                {a > 0.4 &&
                  [...frame.fps]
                    .filter((f) => keyRoles.has(f.role) || f.role === "button")
                    .sort((p, q) => q.c[1] - p.c[1])
                    .map((f, n) => {
                      const cap = f.role === "switch" ? 13 : f.role === "button" ? Math.min(7, Math.max(f.s[0], f.s[1])) : 9;
                      const hh = f.role === "switch" ? 5 : f.role === "button" ? 1.6 : 6;
                      const poly2 = f.role === "switch" ? roundedRect(f.c[0], f.c[1], cap, cap, 2) : roundedRect(f.c[0], f.c[1], cap, cap, cap / 2);
                      const fill = f.role === "switch" ? "#fbfbfa" : f.role === "button" ? "#3b3b3b" : "#555";
                      return <Prism key={`k${n}${f.ref}`} poly={poly2} z0={lidZ} z1={lidZ + hh * clamp01((a - 0.4) / 0.6)} fill={fill} stroke={shade(fill, 0.55)} />;
                    })}
              </g>
            );
          })}
      </g>
    </svg>
  );
}

function viewBox(prep: Prepared): [number, number, number, number] {
  const [x0, y0, x1, y1] = prep.box;
  const pad = 12;
  const top = -y1 * K - (prep.caseH + FLOAT_Z + 12) * Z - pad;
  const bottom = -y0 * K + pad;
  return [x0 - pad, top, x1 - x0 + 2 * pad, bottom - top];
}

/** Build mm to pixels inside a box of w x h showing this viewBox with xMidYMid meet. */
function toPx(vb: [number, number, number, number], w: number, h: number, p: V2): { x: number; y: number } {
  const s = Math.min(w / vb[2], h / vb[3]);
  const ox = (w - vb[2] * s) / 2;
  const oy = (h - vb[3] * s) / 2;
  return { x: ox + (p[0] - vb[0]) * s, y: oy + (p[1] - vb[1]) * s };
}

/** A finished build as a still, for gallery cards that have no rendered picture. */
export function BuildStill(props: { build: ReplayBuild; className?: string }) {
  const prep = useMemo(() => prepare(props.build), [props.build]);
  const frame = useMemo(() => frameAt(prep, T.done[0] + 0.4), [prep]);
  return <SceneDrawing prep={prep} frame={frame} className={props.className} />;
}

const SPEED = 1.35; // the replay runs a little faster than the recorded pacing
const TOAST_S = 1.9;
const STAGES = ["Reading the request", "Choosing parts", "Placing the board", "Routing traces", "Shaping the case", "Checks"];

function stageIndex(t: number): number {
  if (t < T.parts[0]) return 0;
  if (t < T.board[0]) return 1;
  if (t < T.route[0]) return 2;
  if (t < T.walls[0]) return 3;
  if (t < T.done[0]) return 4;
  return 5;
}

interface MockToast {
  id: number;
  text: string;
  at: number;
}

export function BuildScene() {
  const still = useMemo(reducedMotion, []);
  const preps = useMemo(() => BUILDS.map(prepare), []);
  const [clock, setClock] = useState({ dev: 0, t: still ? T.done[0] + 0.4 : 0, now: 0 });
  const box = useRef<HTMLDivElement>(null);
  const body = useRef<HTMLDivElement>(null);
  const pill = useRef<HTMLSpanElement>(null);
  const aim = useRef<AgentAim>({ x: 0, y: 0, pressing: false, set: false });
  const toasts = useRef<MockToast[]>([]);
  const lastSay = useRef<string | null>(null);
  const toastN = useRef(0);

  useEffect(() => {
    if (still) return;
    let raf = 0;
    let last = performance.now();
    let dev = 0;
    let t = 0;
    let wall = 0;
    const tick = (now: number) => {
      raf = requestAnimationFrame(tick);
      const dt = Math.min(0.05, (now - last) / 1000) * SPEED;
      last = now;
      t += dt;
      wall += dt;
      if (t >= RUN_S) {
        t = 0;
        dev = (dev + 1) % preps.length;
      }
      setClock({ dev, t, now: wall });
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [still, preps.length]);

  const prep = preps[clock.dev];
  const frame = frameAt(prep, clock.t);

  // each new thing Bara says also pops as a notification, then fades on its own
  if (!still && frame.say && frame.say !== lastSay.current) toasts.current = [...toasts.current, { id: ++toastN.current, text: frame.say, at: clock.now }].slice(-3);
  lastSay.current = frame.say;
  toasts.current = toasts.current.filter((n) => clock.now - n.at < TOAST_S);

  // where the cursor should be, in pixels inside the mock's body (read by the agent every frame):
  // over the prompt in the sidebar while typing, then on the canvas
  const el = box.current;
  const bd = body.current;
  if (el && bd) {
    const b = bd.getBoundingClientRect();
    if (frame.cursor === "prompt") {
      const r = pill.current?.getBoundingClientRect();
      aim.current = r ? { x: r.right - b.left - 10, y: r.bottom - b.top - 4, pressing: false, set: true } : aim.current;
    } else {
      const cr = el.getBoundingClientRect();
      const c = frame.cursor;
      const p = toPx(viewBox(prep), el.clientWidth, el.clientHeight, P(c.x, c.y, c.z));
      aim.current = { x: p.x + cr.left - b.left, y: p.y + cr.top - b.top, pressing: frame.pressing, set: true };
    }
  }

  const typing = clock.t < T.type[1] + 0.3;
  const prompt = still ? prep.build.prompt : prep.build.prompt.slice(0, frame.typed);
  const at = still ? STAGES.length : stageIndex(clock.t);
  return (
    <div className="mk" aria-label={`Bara building ${prep.build.prompt}, replayed from a real build`} role="img">
      <div className="mk-top">
        <span className="mk-brand">bara</span>
        <span className="mk-tabs">
          {preps.map((p, i) => (
            <span key={p.build.id} className={`mk-tab ${i === clock.dev ? "on" : ""}`}>
              {p.build.name}
            </span>
          ))}
        </span>
        <span className="mk-conn">
          <span className="mk-led" />
          Connected
        </span>
        <span className="mk-btn">Export</span>
      </div>
      <div ref={body} className="mk-body">
        <aside className="mk-side">
          <span ref={pill} className="mk-msg">
            {prompt}
            {typing && !still && <span className="bs-caret" />}
          </span>
          <ol className="mk-stages">
            {STAGES.map((st, i) => (
              <li key={st} className={i < at ? "done" : i === at ? "on" : ""}>
                <span className="mk-tick" />
                {i === 5 && i <= at ? frame.stage : st}
              </li>
            ))}
          </ol>
          <span className="mk-count mono">
            {frame.fps.filter((f) => f.appear > 0).length} / {prep.order.length} parts
          </span>
        </aside>
        <div ref={box} className="mk-canvas">
          <SceneDrawing prep={prep} frame={frame} className="bs-svg" />
          <div className="mk-toasts">
            {toasts.current.map((n) => (
              <span key={n.id} className={`mk-toast ${clock.now - n.at > TOAST_S - 0.3 ? "leaving" : ""}`}>
                {n.text}
              </span>
            ))}
          </div>
        </div>
        <SceneAgent aim={aim} still={still} say={null} activity={frame.activity} done={frame.done > 0} hidden={frame.alpha < 0.5} />
      </div>
    </div>
  );
}
