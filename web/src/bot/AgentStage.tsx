// The agent on stage. While a build runs, the bot leaves the prompt bar and
// works the canvas: it glides beside whatever the build is touching and steers a
// small cursor onto it, while the viewport outlines the part in 3D (agentFocus).
// No 2D box: a flat square over the 3D scene read as something odd sitting there. When the build ends
// and the queue is played out it flies home to the prompt bar.
//
// Other features ask it to do things through agentBus.ts (explain a part, act
// out an ask, replays). Those requests play through the same queue and fly the
// bot out from home the same way, build or no build.
//
// Beats come from director.ts; part rects from three/agentTargets. One rAF
// loop moves everything by writing styles to refs; React renders only when the
// beat changes.
import { useEffect, useMemo, useRef, useState } from "react";
import { useApp } from "../state/store";
import { BaraBot } from "./BaraBot";
import { agentEnabled, type AgentTarget, type Beat, type Rect } from "./agent";
import { onAgentDo, setAgentPos } from "./agentBus";
import { beatsFor, enqueue, paceFor } from "./director";
import { speechFor } from "./mood";
import { toggleTrace, useTrace } from "./traceState";
import { canvasRect, partRect } from "../three/agentTargets";
import { clamp, lerp, PRESETS, reducedMotion, Spring, wander, type SpringCfg } from "./spring";
import "./agentStage.css";

/** The stage bot's rendered size; it scales to the docked bot's size at home. */
const BOT = 44;
/** Gap between the target box and the bot. */
const GAP = 14;
/** Padding of the selection box around its target. */
const PAD = 6;
/** No tab switching or scrolling for this long after the user touches anything. */
const HANDS_OFF_MS = 5000;
/** Out of things to do and the stream quiet this long: fly home. */
const QUIET_MS = 1200;
/** The bot never acts out something that happened longer ago than this: older glances are skipped. */
const LAG_MAX_MS = 6000;
/** Behind by this much: every beat gets the shortest dwell. */
const LAG_HURRY_MS = 3000;
/** Events that fly the bot out after the build is over (edits land on a finished build). */
const AFTER_BUILD = new Set(["edit.applied", "edit.rejected"]);
/** Store speech while the stage drives the bubble (mirrors BaraBot): one line this often, these always. */
const SPEECH_GAP_MS = 3000;
const ALWAYS_SPEAK = new Set(["build.done", "build.failed", "clarify.request"]);

// Slow, nearly critically damped glides: the bot drifts between major steps instead of darting.
const FLOAT: SpringCfg = { stiffness: 32, damping: 11 }; // the bot: floaty, trails the cursor
const STEER: SpringCfg = { stiffness: 70, damping: 16 }; // the cursor: gets there first
/** The cursor's arrowhead: tip at (3, 3), wings out to the right and down, a notch at the back. */
const ARROW = "M3 3 L17.2 8.9 L10.5 10.5 L8.9 17.2 Z";
const FRAME: SpringCfg = { stiffness: 90, damping: 19 }; // the selection box

type Phase = "home" | "out" | "returning";


function hash(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619);
  return h >>> 0;
}

/** A Manhattan route across the box, in 0..100 box units: [x, y] corners. */
function tracePoints(id: string): [number, number][] {
  const h = hash(id);
  const y0 = 20 + (h % 60);
  const x1 = 18 + ((h >> 6) % 25);
  const y1 = 15 + ((h >> 11) % 70);
  const x2 = 50 + ((h >> 17) % 30);
  const y2 = 15 + ((h >> 22) % 70);
  return [
    [3, y0],
    [x1, y0],
    [x1, y1],
    [x2, y1],
    [x2, y2],
    [97, y2],
  ];
}

/** Point a fraction t (0..1) of the way along a polyline. */
function along(pts: [number, number][], t: number): [number, number] {
  const seg: number[] = [];
  let total = 0;
  for (let i = 1; i < pts.length; i++) {
    const d = Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]);
    seg.push(d);
    total += d;
  }
  let left = clamp(t, 0, 1) * total;
  for (let i = 0; i < seg.length; i++) {
    if (left <= seg[i] || i === seg.length - 1) {
      const k = seg[i] ? clamp(left / seg[i], 0, 1) : 0;
      return [lerp(pts[i][0], pts[i + 1][0], k), lerp(pts[i][1], pts[i + 1][1], k)];
    }
    left -= seg[i];
  }
  return pts[pts.length - 1];
}

function domEl(key: string): HTMLElement | null {
  return document.querySelector<HTMLElement>(`[data-agent="${CSS.escape(key)}"]`);
}

function domRect(key: string): Rect | null {
  const el = domEl(key);
  if (!el) return null;
  const r = el.getBoundingClientRect();
  if (r.width < 2 || r.height < 2) return null; // hidden (closed tab, collapsed section)
  return { x: r.left, y: r.top, w: r.width, h: r.height };
}

const CODE_TABS = new Set(["connections", "board", "firmware"]);

/** A code sub-tab target with no open of its own still needs its panel showing. */
function impliedOpen(t: AgentTarget): Beat["open"] {
  if (t.kind !== "dom") return undefined;
  const [kind, id] = t.key.split(":");
  if (kind === "codetab" && CODE_TABS.has(id)) return { rightTab: "code", codeTab: id as "connections" | "board" | "firmware" };
  return undefined;
}

/** Where a target sits on screen right now, falling back to the canvas. */
function resolve(t: AgentTarget | null): Rect | null {
  if (t?.kind === "part") {
    const r = partRect(t.id);
    if (r && r.w > 1 && r.h > 1) return r;
    const row = domRect(`row:${t.id}`);
    if (row) return row;
  } else if (t?.kind === "dom") {
    const r = domRect(t.key);
    if (r) return r;
    // A code sub-tab while the Code tab is closed (hands off): point at the Code tab instead.
    if (t.key.startsWith("codetab:")) {
      const tab = domRect("tab:code");
      if (tab) return tab;
    }
  }
  return domRect("viewport") ?? canvasRect();
}

function homeRect(): Rect | null {
  const el = document.querySelector<HTMLElement>(".promptbar.docked .prompt-bot") ?? document.querySelector<HTMLElement>(".prompt-bot");
  if (!el) return null;
  const r = el.getBoundingClientRect();
  return { x: r.left, y: r.top, w: r.width, h: r.height };
}

/** A spot for the bot (its centre) just outside r, on screen, not over it. */
function perch(r: Rect, fromX: number): { x: number; y: number } {
  const W = window.innerWidth;
  const H = window.innerHeight;
  const half = BOT / 2;
  const fits = (x: number, y: number) => x - half >= 8 && x + half <= W - 8 && y - half >= 8 && y + half <= H - 8;
  const left = { x: r.x - GAP - half, y: r.y + half };
  const right = { x: r.x + r.w + GAP + half, y: r.y + half };
  const leftLow = { x: left.x, y: r.y + r.h - half };
  const rightLow = { x: right.x, y: r.y + r.h - half };
  const preferRight = fromX > r.x + r.w / 2;
  const order = preferRight ? [right, left, rightLow, leftLow] : [left, right, leftLow, rightLow];
  for (const p of order) if (fits(p.x, p.y)) return p;
  // Too big to sit beside (the whole canvas): tuck into its top-left corner, under the label.
  return { x: clamp(r.x + half + 14, half + 8, W - half - 8), y: clamp(r.y + half + 34, half + 8, H - half - 8) };
}

export function AgentStage() {
  const enabled = useMemo(agentEnabled, []);
  const screen = useApp((s) => s.screen);
  if (!enabled || screen !== "workspace") return null;
  return <Stage />;
}

function Stage() {
  const [beat, setBeat] = useState<Beat | null>(null);
  const [phase, setPhase] = useState<Phase>("home");
  const traceOpen = useTrace((s) => s.open);
  const stage = useRef<HTMLDivElement>(null);
  const cursorEl = useRef<HTMLDivElement>(null);
  const rippleEl = useRef<HTMLDivElement>(null);
  const botEl = useRef<HTMLDivElement>(null);
  const botBody = useRef<HTMLDivElement>(null);
  const queue = useRef<Beat[]>([]);
  /** When each queued beat came in, to keep the bot from lagging far behind. */
  const arrived = useRef(new WeakMap<Beat, number>());
  const phaseRef = useRef<Phase>("home");
  const lastTouch = useRef(-Infinity);
  const lastEvent = useRef(0);
  /** Something other than a running build wants the bot out (a bus request, an edit). */
  const wantOut = useRef(false);
  /** Cut the current beat short (an interrupting request). */
  const cut = useRef(false);
  // Speech: null leaves the bubble to BaraBot's own store-driven lines. Once a beat speaks,
  // the stage drives the bubble for the rest of the flight and forwards the store's lines too.
  const [say, setSay] = useState<{ text: string; n: number } | null>(null);
  const sayN = useRef(0);
  const sayOn = useRef(false);
  const speak = (text: string) => {
    sayOn.current = true;
    setSay({ text, n: ++sayN.current });
  };

  const push = (beats: Beat[]) => {
    const now = performance.now();
    for (const b of beats) if (!arrived.current.has(b)) arrived.current.set(b, now);
    queue.current = enqueue(queue.current, beats);
  };

  // Beats from the event stream.
  useEffect(() => {
    let seen = useApp.getState().log.at(-1)?.id ?? 0;
    let lastSpoke = 0;
    // once() beats (case, board, firmware) play one time per build, however often their events repeat.
    let onceBuild: string | null = null;
    const played = new Set<string>();
    const fresh1 = (b: Beat) => !b.id.startsWith("once:") || (!played.has(b.id) && !!played.add(b.id));
    return useApp.subscribe((s) => {
      if ((s.build?.build_id ?? null) !== onceBuild) {
        onceBuild = s.build?.build_id ?? null;
        played.clear();
      }
      const last = s.log.at(-1)?.id ?? seen;
      if (last === seen) return;
      // Only the canvas on screen: background canvases keep building without the bot.
      const fresh = s.log.filter((e) => e.id > seen && e.dir === "in" && (!e.buildId || e.buildId === s.build?.build_id));
      seen = last;
      if (!fresh.length) return;
      lastEvent.current = performance.now();
      const running = s.build?.status === "running" || s.build?.status === "awaiting_input";
      for (const e of fresh) {
        if (sayOn.current) {
          const line = speechFor(e);
          const t = performance.now();
          if (line && (ALWAYS_SPEAK.has(e.type) || t - lastSpoke > SPEECH_GAP_MS)) {
            lastSpoke = t;
            speak(line);
          }
        }
        // After the build, at home or flying home: only edits bring the bot out; stragglers
        // (late firmware progress) are let go.
        const after = AFTER_BUILD.has(e.type);
        if (phaseRef.current !== "out" && !running && !after) continue;
        const beats = beatsFor(e, useApp.getState().build).filter(fresh1);
        if (!beats.length) continue;
        if (after && !running) wantOut.current = true;
        push(beats);
      }
    });
  }, []);

  // Requests from the side door (agentBus): same queue, same flight.
  useEffect(
    () =>
      onAgentDo((r) => {
        if (!r.beats.length) return;
        const beats = r.say ? [{ ...r.beats[0], say: r.beats[0].say ?? r.say }, ...r.beats.slice(1)] : r.beats;
        if (r.interrupt) {
          queue.current = [];
          cut.current = true;
        }
        lastEvent.current = performance.now();
        wantOut.current = true;
        push(beats);
      }),
    [],
  );

  // The user's hands: while they are busy, the agent does not move their UI.
  useEffect(() => {
    const touch = () => (lastTouch.current = performance.now());
    const opts = { capture: true, passive: true } as const;
    window.addEventListener("pointerdown", touch, opts);
    window.addEventListener("wheel", touch, opts);
    window.addEventListener("keydown", touch, opts);
    return () => {
      window.removeEventListener("pointerdown", touch, opts);
      window.removeEventListener("wheel", touch, opts);
      window.removeEventListener("keydown", touch, opts);
    };
  }, []);

  // Leaving the workspace mid-build: hand the bot back.
  useEffect(
    () => () => {
      setAgentPos(null);
      if (useApp.getState().agentOut) useApp.setState({ agentOut: false, agentFocus: null });
    },
    [],
  );

  // The one animation loop.
  useEffect(() => {
    const bx = new Spring(0, FLOAT);
    const by = new Spring(0, FLOAT);
    const cx = new Spring(0, STEER);
    const cy = new Spring(0, STEER);
    const box = { x: new Spring(0, FRAME), y: new Spring(0, FRAME), w: new Spring(0, FRAME), h: new Spring(0, FRAME) };
    const tilt = new Spring(0, PRESETS.smooth);
    const squash = new Spring(0, PRESETS.wobbly);
    const hop = new Spring(0, PRESETS.bouncy);
    const scale = new Spring(1, PRESETS.smooth);
    const press = new Spring(1, PRESETS.wobbly);
    const all = [bx, by, cx, cy, box.x, box.y, box.w, box.h, tilt, squash, hop, scale, press];

    let cur: Beat | null = null;
    let beatAt = 0;
    let boxShown = false;
    let pressed = false;
    let landed = true;
    let lastSpeed = 0;
    let trace: [number, number][] = [];
    let last = performance.now();
    let raf = 0;

    const setPhaseBoth = (p: Phase) => {
      phaseRef.current = p;
      setPhase(p);
    };

    const handsOff = () => performance.now() - lastTouch.current < HANDS_OFF_MS;

    const startBeat = (next: Beat | null, now: number, behindMs = 0) => {
      // Dwell shrinks as the queue fills or the bot falls behind, so it keeps up.
      const b = next && { ...next, dwellMs: behindMs > LAG_HURRY_MS ? paceFor(next, Infinity) : paceFor(next, queue.current.length + 1) };
      cur = b;
      beatAt = now;
      pressed = false;
      landed = false;
      cut.current = false;
      setBeat(b);
      if (!b) return;
      if (b.say) speak(b.say);
      trace = b.action === "trace" ? tracePoints(b.id) : [];
      useApp.setState({ agentFocus: b.target.kind === "part" ? b.target.id : null });
      const free = !handsOff();
      const open = b.open ?? impliedOpen(b.target);
      if (open && free) {
        const s = useApp.getState();
        const patch: { rightTab?: typeof s.rightTab; codeTab?: typeof s.codeTab } = {};
        if (open.rightTab && open.rightTab !== s.rightTab) patch.rightTab = open.rightTab;
        if (open.codeTab && open.codeTab !== s.codeTab) patch.codeTab = open.codeTab;
        if (patch.rightTab || patch.codeTab) useApp.setState(patch);
      }
      const key = b.target.kind === "dom" ? b.target.key : `row:${b.target.id}`;
      if (free && (b.target.kind === "dom" || !partRect(b.target.id))) {
        // After the tab it may have opened has rendered.
        window.setTimeout(() => {
          if (handsOff()) return;
          domEl(key)?.scrollIntoView({ block: "nearest", behavior: reducedMotion() ? "auto" : "smooth" });
        }, 80);
      }
      if (b.action === "cheer" && !reducedMotion()) {
        hop.impulse(-520);
        window.setTimeout(() => squash.impulse(-6), 330);
        window.setTimeout(() => hop.impulse(-430), 520);
        window.setTimeout(() => squash.impulse(-5), 830);
      }
    };

    const launch = (now: number, byBuild: boolean) => {
      const home = homeRect();
      const x = home ? home.x + home.w / 2 : window.innerWidth / 2;
      const y = home ? home.y + home.h / 2 : window.innerHeight - 90;
      for (const [s, v] of [
        [bx, x],
        [by, y],
        [cx, x + 10],
        [cy, y + 8],
      ] as const) {
        s.value = s.target = v;
        s.velocity = 0;
      }
      scale.value = scale.target = home ? home.w / BOT : 0.8;
      if (!reducedMotion()) {
        by.impulse(-900); // springs up out of the bar
        squash.impulse(7);
      }
      boxShown = false;
      // The click that started the build does not count as hands on; a hover or click that asked
      // for the bot (bus request) does, so it does not switch the user's tabs under them.
      if (byBuild) lastTouch.current = -Infinity;
      useApp.setState({ agentOut: true });
      setPhaseBoth("out");
      startBeat(null, now);
    };

    const goHome = () => {
      useApp.setState({ agentOut: false, agentFocus: null });
      queue.current = [];
      wantOut.current = false;
      sayOn.current = false;
      setSay(null);
      setAgentPos(null);
      setPhaseBoth("home");
      startBeat(null, performance.now());
    };

    const frame = (now: number) => {
      raf = requestAnimationFrame(frame);
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      const st = useApp.getState();
      const status = st.build?.status;
      const running = status === "running" || status === "awaiting_input";
      const reduced = reducedMotion();

      const asked = wantOut.current && queue.current.length > 0;
      if (phaseRef.current !== "out" && (status === "running" || asked)) {
        wantOut.current = false;
        if (phaseRef.current === "home") launch(now, status === "running");
        else setPhaseBoth("out");
      }
      const phaseNow = phaseRef.current;
      if (phaseNow === "home") {
        if (stage.current) stage.current.dataset.on = "0";
        return;
      }
      if (stage.current) stage.current.dataset.on = "1";

      // Next beat when this one has had its time (or an interrupting request cut it short).
      const done = !cur || cut.current || now - beatAt >= cur.dwellMs;
      if (phaseNow === "out" && done) {
        const q = queue.current;
        const age = (x: Beat) => now - (arrived.current.get(x) ?? now);
        // Too far behind: skip glances that are old news (never problems, cheers or lines to say).
        while (q.length > 1 && age(q[0]) > LAG_MAX_MS && !q[0].bad && !q[0].say && q[0].action !== "cheer") q.shift();
        const next = q.shift();
        if (next) startBeat(next, now, age(next));
        // Home only once the build is over, the queue is played out and the stream has gone quiet
        // (some events trail build.done), so it never flies home and straight back out.
        else if (!running && (!cur || cut.current || now - beatAt >= cur.dwellMs + 350) && now - lastEvent.current > QUIET_MS) {
          setPhaseBoth("returning");
          startBeat(null, now);
          useApp.setState({ agentFocus: null });
        }
      }
      const b = cur;
      const t = b ? (now - beatAt) / 1000 : 0;

      // Where everything wants to be.
      const target = phaseRef.current === "returning" ? null : resolve(b?.target ?? null);
      if (target) {
        let pad = PAD;
        if (b?.action === "pick") pad = pressed ? 2 : 12;
        const W = window.innerWidth;
        const H = window.innerHeight;
        const x0 = clamp(target.x - pad, 2, W - 4);
        const y0 = clamp(target.y - pad, 2, H - 4);
        const x1 = clamp(target.x + target.w + pad, x0 + 2, W - 2);
        const y1 = clamp(target.y + target.h + pad, y0 + 2, H - 2);
        box.x.target = x0;
        box.y.target = y0;
        box.w.target = x1 - x0;
        box.h.target = y1 - y0;
        if (!boxShown && b) {
          // First box: start from a point at the cursor, so it grows out of it.
          box.x.value = cx.value;
          box.y.value = cy.value;
          box.w.value = 0;
          box.h.value = 0;
          boxShown = true;
        }
        // The cursor: into the box, riding the action.
        let px = x0 + (x1 - x0) * 0.58;
        let py = y0 + (y1 - y0) * 0.52;
        if (b?.action === "scan") {
          const ph = (t / 1.2) % 1;
          px = x1 - Math.min(18, (x1 - x0) * 0.2);
          py = lerp(y0 + 4, y1 - 4, ph);
        } else if (b?.action === "trace" && trace.length) {
          const drawMs = Math.min(b.dwellMs * 0.7, 1400);
          const [u, v] = along(trace, ((now - beatAt) / drawMs) % 1.6);
          px = x0 + ((x1 - x0) * u) / 100;
          py = y0 + ((y1 - y0) * v) / 100;
        } else if (b?.action === "type") {
          const flip = x1 + 190 > W; // the code chip sits under the box then (agentStage.css)
          px = flip ? x1 - 12 : x1 + 4;
          py = flip ? y1 + 22 : y0 + 14;
        } else if (b?.action === "check") {
          px = x1 - 6;
          py = y0 + 6;
        }
        cx.target = clamp(px, 4, W - 16);
        cy.target = clamp(py, 4, H - 20);
        const p = perch({ x: x0, y: y0, w: x1 - x0, h: y1 - y0 }, bx.value);
        const bob = reduced ? 0 : 2.5 * wander(now / 900, 3);
        bx.target = p.x;
        by.target = p.y + bob;
        scale.target = 1;
      } else {
        // Flying home.
        const home = homeRect();
        const hx = home ? home.x + home.w / 2 : window.innerWidth / 2;
        const hy = home ? home.y + home.h / 2 : window.innerHeight - 90;
        bx.target = hx;
        by.target = hy;
        cx.target = hx;
        cy.target = hy;
        scale.target = home ? home.w / BOT : 0.8;
        if (phaseRef.current === "returning" && (reduced || (Math.hypot(bx.value - hx, by.value - hy) < 3 && Math.hypot(bx.velocity, by.velocity) < 40))) {
          goHome();
          return;
        }
      }

      // Pick: press once the cursor has arrived.
      if (b?.action === "pick" && !pressed && Math.hypot(cx.value - cx.target, cy.value - cy.target) < 4) {
        pressed = true;
        if (!reduced) press.impulse(-9);
        const rip = rippleEl.current;
        if (rip) {
          rip.style.transform = `translate(${cx.value.toFixed(1)}px, ${cy.value.toFixed(1)}px)`;
          rip.classList.remove("on");
          void rip.offsetWidth; // restart the animation
          rip.classList.add("on");
        }
      }

      if (reduced) {
        for (const s of all) {
          s.value = s.target;
          s.velocity = 0;
        }
      } else {
        for (const s of all) s.step(dt);
      }

      // The bot leans into its travel, stretches with speed and squashes on arrival.
      const speed = Math.hypot(bx.velocity, by.velocity);
      tilt.target = reduced ? 0 : clamp(bx.velocity * 0.035, -16, 16);
      if (!landed && lastSpeed > 140 && speed < 50) {
        landed = true;
        if (!reduced) squash.impulse(-6);
      }
      lastSpeed = speed;
      const stretch = reduced ? 0 : clamp(speed / 3000, 0, 0.12);
      const sq = squash.value * 0.03;
      const sx = scale.value * (1 + sq - stretch * 0.5);
      const sy = scale.value * (1 - sq + stretch);

      // Where the stage bot is, for features that point at it (agentBus.agentPos).
      const size = BOT * scale.value;
      setAgentPos(phaseRef.current === "home" ? null : { x: bx.value - size / 2, y: by.value - size / 2, w: size, h: size });
      if (botEl.current) botEl.current.style.transform = `translate(${(bx.value - BOT / 2).toFixed(1)}px, ${(by.value - BOT / 2 + hop.value * 0.06).toFixed(1)}px)`;
      if (botBody.current) {
        // Home size on the whole bot (bubbles included); lean and squash on the oval only, so speech never tilts.
        const bs = botBody.current.style;
        bs.transform = `scale(${scale.value.toFixed(3)})`;
        bs.setProperty("--as-rot", `${tilt.value.toFixed(2)}deg`);
        bs.setProperty("--as-sx", (sx / scale.value).toFixed(3));
        bs.setProperty("--as-sy", (sy / scale.value).toFixed(3));
      }
      if (cursorEl.current) {
        // it tips a little into the way it is travelling, and settles back when it stops
        const lean = clamp(cx.velocity * 0.012 - cy.velocity * 0.006, -14, 14);
        cursorEl.current.style.transform = `translate(${cx.value.toFixed(1)}px, ${cy.value.toFixed(1)}px) rotate(${lean.toFixed(2)}deg) scale(${clamp(press.value, 0.6, 1.3).toFixed(3)})`;
        cursorEl.current.dataset.on = phaseRef.current === "out" ? "1" : "0";
      }
    };
    raf = requestAnimationFrame(frame);
    return () => cancelAnimationFrame(raf);
  }, []);


  return (
    <div ref={stage} className="agent-stage" data-on="0" aria-hidden="true">
      <div ref={rippleEl} className="as-ripple" data-bad={beat?.bad ? "1" : "0"} />
      <div ref={cursorEl} className="as-cursor" data-on="0" data-bad={beat?.bad ? "1" : "0"}>
        {/* A notched arrowhead: a rim in the page colour under a lit accent body; the tip is the element origin. */}
        <svg viewBox="0 0 20 20" width="20" height="20">
          <defs>
            <linearGradient id="as-cur-g" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0" className="as-cur-lit" />
              <stop offset="1" className="as-cur-deep" />
            </linearGradient>
          </defs>
          <path className="as-cur-rim" d={ARROW} />
          <path className="as-cur-body" d={ARROW} />
          <path className="as-cur-shine" d="M5.2 5.2 L11.6 7.9" />
        </svg>
      </div>
      <div ref={botEl} className="as-bot" data-phase={phase} onClick={toggleTrace}>
        <div ref={botBody} className="as-bot-body">
          {phase !== "home" && <BaraBot size={BOT} bubbles say={say} typing={traceOpen} />}
        </div>
      </div>
    </div>
  );
}
