// Labelled exploded hold: one label per part in a right-hand column, each with
// a leader line to a dot on the part. Positions are written straight to the
// DOM every frame (no React re-render); the list itself changes only with the
// build.
import { useEffect, useRef } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import * as THREE from "three";
import { focusAmount, stage } from "./stage";
import { focusPart, useApp } from "../state/store";

export interface LabelRow {
  key: string;
  title: string;
  detail: string;
  sub: string;
  generated: boolean;
}

interface Slot {
  row: HTMLDivElement | null;
  line: SVGLineElement | null;
  dot: SVGCircleElement | null;
}

const slots = new Map<string, Slot>();
let overlayEl: HTMLDivElement | null = null;
let behindEl: HTMLDivElement | null = null;

/** 0 when assembled, 1 when the explode is held open. */
export function labelOpacity(explode: number): number {
  return Math.min(1, Math.max(0, (explode - 0.82) / 0.14));
}

/** DOM overlay, placed over the canvas inside .viewport. */
export function LabelOverlay(props: { rows: LabelRow[]; color: string; muted: string; line: string; accent: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    overlayEl = ref.current;
    return () => {
      overlayEl = null;
    };
  }, []);
  return (
    <div ref={ref} style={{ position: "absolute", inset: 0, pointerEvents: "none", opacity: 0, zIndex: 3, overflow: "hidden" }}>
      <svg aria-hidden width="100%" height="100%" style={{ position: "absolute", inset: 0 }}>
        {props.rows.map((r) => (
          <g key={r.key}>
            <line
              ref={(el) => {
                const s = slots.get(r.key) ?? { row: null, line: null, dot: null };
                s.line = el;
                slots.set(r.key, s);
              }}
              stroke={props.line}
              strokeWidth={1}
            />
            <circle
              ref={(el) => {
                const s = slots.get(r.key) ?? { row: null, line: null, dot: null };
                s.dot = el;
                slots.set(r.key, s);
              }}
              r={3}
              fill={props.color}
            />
          </g>
        ))}
      </svg>
      {props.rows.map((r) => (
        <div
          key={r.key}
          ref={(el) => {
            const s = slots.get(r.key) ?? { row: null, line: null, dot: null };
            s.row = el;
            slots.set(r.key, s);
          }}
          role="button"
          className="explode-label"
          // a label picks its part: hovering outlines it, clicking pulls it out into focus
          onPointerEnter={() => useApp.setState({ hoverLabel: r.key })}
          onPointerLeave={() => {
            if (useApp.getState().hoverLabel === r.key) useApp.setState({ hoverLabel: null });
          }}
          onClick={() => {
            useApp.setState({ hoverLabel: null });
            focusPart(r.key);
          }}
          style={{ position: "absolute", left: 0, top: 0, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", lineHeight: 1.15, willChange: "transform", pointerEvents: "none", cursor: "pointer" }}
        >
          <div style={{ font: "600 14px/1.2 var(--font-sans, system-ui, sans-serif)", color: props.color, overflow: "hidden", textOverflow: "ellipsis" }}>
            {r.title}
            {r.detail && <span style={{ fontWeight: 500, color: props.muted, marginLeft: 8 }}>{r.detail}</span>}
          </div>
          <div style={{ font: "400 11.5px/1.3 var(--font-sans, system-ui, sans-serif)", color: r.generated ? props.accent : props.muted }}>{r.sub}</div>
        </div>
      ))}
      <div
        ref={(el) => {
          behindEl = el;
        }}
        style={{ position: "absolute", left: 0, top: 0, whiteSpace: "nowrap", font: "400 11.5px/1.3 var(--font-sans, system-ui, sans-serif)", color: props.muted, opacity: 0.8, visibility: "hidden" }}
      />
    </div>
  );
}

const tmp = new THREE.Vector3();
const ray = new THREE.Raycaster();
const camPos = new THREE.Vector3();
const lastCam = new THREE.Matrix4();

/** Per label: whether it is in view now, how long it has been hidden, its faded opacity, and which anchor it uses. */
interface Seen {
  visible: boolean;
  hiddenFor: number;
  alpha: number;
  anchor: number;
}
const seen = new Map<string, Seen>();

/** Vertical room one two-line label needs in the column. */
const LABEL_GAP = 40;

/**
 * Label heights for anchors at `ys` (sorted top to bottom): each label sits level with its anchor
 * where it can, so leader lines run nearly flat and do not cross, and is pushed apart just enough
 * to keep `gap` between rows inside [top, bottom]. A crowded column shrinks the gap to fit.
 */
export function spreadLabels(ys: number[], top: number, bottom: number, gap: number): number[] {
  const n = ys.length;
  if (!n) return [];
  const g = n > 1 ? Math.min(gap, Math.max(0, bottom - top) / (n - 1)) : 0;
  const out = ys.map((y) => Math.min(Math.max(y, top), bottom));
  for (let i = 1; i < n; i++) out[i] = Math.max(out[i], out[i - 1] + g);
  out[n - 1] = Math.min(out[n - 1], bottom);
  for (let i = n - 2; i >= 0; i--) out[i] = Math.min(out[i], out[i + 1] - g);
  out[0] = Math.max(out[0], top);
  for (let i = 1; i < n; i++) out[i] = Math.max(out[i], out[i - 1] + g);
  return out;
}

function crosses(ax: number, ay: number, by: number, cx: number, cy: number, dy: number, col: number): boolean {
  // segment (ax,ay)->(col,by) against (cx,cy)->(col,dy)
  const side = (px: number, py: number, qx: number, qy: number, rx: number, ry: number) => Math.sign((qx - px) * (ry - py) - (qy - py) * (rx - px));
  return side(ax, ay, col, by, cx, cy) !== side(ax, ay, col, by, col, dy) && side(cx, cy, col, dy, ax, ay) !== side(cx, cy, col, dy, col, by);
}

/**
 * Reorders anchors over the fixed label slots `ys` (in place) so neighbouring leader lines to the
 * column at `col` stop crossing: adjacent pairs that cross swap slots, a few passes over the list.
 */
export function untangle<P extends { x: number; y: number }>(pts: P[], ys: number[], col: number): void {
  for (let pass = 0; pass < pts.length; pass++) {
    let swapped = false;
    for (let i = 0; i + 1 < pts.length; i++) {
      const a = pts[i];
      const b = pts[i + 1];
      if (crosses(a.x, a.y, ys[i], b.x, b.y, ys[i + 1], col)) {
        pts[i] = b;
        pts[i + 1] = a;
        swapped = true;
      }
    }
    if (!swapped) return;
  }
}

const FADE_S = 0.18;
const HIDE_AFTER_S = 0.15;
const CHECK_EVERY_S = 0.12;

function isUnder(obj: THREE.Object3D | null, owner: THREE.Object3D): boolean {
  for (let o = obj; o; o = o.parent) if (o === owner) return true;
  return false;
}

/**
 * True when nothing from another part sits between the camera and the point: the first mesh a ray
 * from the camera meets is the anchor's own part, or there is none before the point.
 */
function inView(point: THREE.Vector3, owner: THREE.Object3D | null, root: THREE.Object3D): boolean {
  const dist = camPos.distanceTo(point);
  ray.set(camPos, tmp.copy(point).sub(camPos).normalize());
  ray.near = 0;
  ray.far = dist * 0.995;
  const hits = ray.intersectObject(root, true);
  for (const h of hits) {
    if (!(h.object as THREE.Mesh).isMesh || !h.object.visible) continue;
    const m = (h.object as THREE.Mesh).material as THREE.Material | THREE.Material[];
    // see-through shells (the assembled case) don't hide what is inside them
    if (!Array.isArray(m) && m.transparent && m.opacity < 0.5) continue;
    return owner ? isUnder(h.object, owner) : false;
  }
  return true;
}

/**
 * Inside the Canvas: projects anchors and lays the label column out each frame. A label shows only
 * while its part is in view from the camera; turning the model brings hidden ones back.
 */
export function LabelProjector() {
  const { camera, size, invalidate } = useThree();
  const since = useRef(CHECK_EVERY_S);
  useFrame((_, dt) => {
    const el = overlayEl;
    if (!el) return;
    // labels step aside while a part is in focus
    const alpha = labelOpacity(stage.explode) * (1 - focusAmount());
    el.style.opacity = String(alpha);
    // rows take clicks only while the explode is held open, never as invisible hit areas
    const live = alpha > 0.5 ? "auto" : "none";
    for (const s of slots.values()) if (s.row && s.row.style.pointerEvents !== live) s.row.style.pointerEvents = live;
    if (alpha <= 0) return;
    const w = size.width;
    const h = size.height;
    // Occlusion is re-tested a few times a second while the view or the explode changes, not every frame.
    since.current += dt;
    const camMoved = !lastCam.equals(camera.matrixWorld);
    const check = stage.root !== null && since.current >= CHECK_EVERY_S && (camMoved || stage.moving || seen.size === 0 || [...seen.values()].some((v) => v.hiddenFor > 0 && v.visible));
    if (check) {
      since.current = 0;
      lastCam.copy(camera.matrixWorld);
      camera.getWorldPosition(camPos);
    }
    const pts: { key: string; x: number; y: number; a: number }[] = [];
    let behind = 0;
    for (const [key, list] of stage.anchors) {
      if (!list.length || !slots.has(key)) continue;
      const st = seen.get(key) ?? { visible: true, hiddenFor: 0, alpha: 1, anchor: 0 };
      seen.set(key, st);
      if (check && stage.root) {
        // the anchor in view closest to the label column wins, so its line crosses as little as possible
        let best = -1;
        let bestX = -Infinity;
        for (let i = 0; i < Math.min(list.length, 4); i++) {
          const a = list[i];
          const wp = a.world();
          if (!inView(wp, a.owner?.() ?? null, stage.root)) continue;
          const sx = tmp.copy(wp).project(camera).x;
          if (sx > bestX) {
            bestX = sx;
            best = i;
          }
        }
        if (best >= 0) {
          st.anchor = best;
          st.hiddenFor = 0;
          st.visible = true;
        } else {
          st.hiddenFor += CHECK_EVERY_S;
          if (st.hiddenFor >= HIDE_AFTER_S) st.visible = false;
        }
      }
      const target = st.visible ? 1 : 0;
      st.alpha += Math.sign(target - st.alpha) * Math.min(Math.abs(target - st.alpha), dt / FADE_S);
      if (!st.visible) behind++;
      if (st.alpha <= 0.01) continue;
      const anchor = list[Math.min(st.anchor, list.length - 1)];
      tmp.copy(anchor.world()).project(camera);
      pts.push({ key, x: ((tmp.x + 1) / 2) * w, y: ((1 - tmp.y) / 2) * h, a: st.alpha });
    }
    for (const key of seen.keys()) if (!stage.anchors.has(key)) seen.delete(key);
    // the canvas draws on demand: keep frames coming while a label fades or waits to hide
    if ([...seen.values()].some((v) => (v.visible ? v.alpha < 1 || v.hiddenFor > 0 : v.alpha > 0))) invalidate();
    pts.sort((a, b) => a.y - b.y);
    // Rows whose part has no anchor this frame (toggled off, hidden from view, or a case without a bezel) stay hidden.
    const shown = new Map(pts.map((p) => [p.key, p.a]));
    for (const [key, s] of slots) {
      const a = shown.get(key);
      const v = a !== undefined ? "visible" : "hidden";
      for (const node of [s.row, s.line, s.dot]) {
        if (!node) continue;
        if (node.style.visibility !== v) node.style.visibility = v;
        if (a !== undefined) node.style.opacity = a.toFixed(3);
      }
    }
    const maxX = pts.reduce((m, p) => Math.max(m, p.x), 0);
    const colX = Math.min(Math.max(maxX + 48, w * 0.5), w - 300);
    const top = Math.max(16, h * 0.27);
    const bottom = Math.min(h - 40, h - 150);
    const n = pts.length;
    const ys = spreadLabels(
      pts.map((p) => p.y),
      top,
      bottom,
      LABEL_GAP,
    );
    const last = n ? ys[n - 1] : top;
    untangle(pts, ys, colX);
    pts.forEach((p, i) => {
      const s = slots.get(p.key);
      if (!s) return;
      const y = ys[i];
      if (s.row) {
        s.row.style.transform = `translate(${colX + 8}px, ${y - 9}px)`;
        s.row.style.maxWidth = `${Math.max(120, w - colX - 20)}px`;
      }
      if (s.line) {
        s.line.setAttribute("x1", String(p.x));
        s.line.setAttribute("y1", String(p.y));
        s.line.setAttribute("x2", String(colX));
        s.line.setAttribute("y2", String(y));
      }
      if (s.dot) {
        s.dot.setAttribute("cx", String(p.x));
        s.dot.setAttribute("cy", String(p.y));
      }
    });
    if (behindEl) {
      const v = behind > 0 && n > 0 ? "visible" : "hidden";
      if (behindEl.style.visibility !== v) behindEl.style.visibility = v;
      if (v === "visible") {
        behindEl.textContent = `+${behind} behind other parts, turn the model to see ${behind === 1 ? "it" : "them"}`;
        behindEl.style.transform = `translate(${colX + 8}px, ${last + LABEL_GAP * 0.7}px)`;
      }
    }
  });
  return null;
}
