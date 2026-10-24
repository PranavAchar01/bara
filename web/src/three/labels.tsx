// Labelled exploded hold: one label per part in a right-hand column, each with
// a leader line to a dot on the part. Positions are written straight to the
// DOM every frame (no React re-render); the list itself changes only with the
// build.
import { useEffect, useRef } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import * as THREE from "three";
import { stage } from "./stage";

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
    <div ref={ref} aria-hidden style={{ position: "absolute", inset: 0, pointerEvents: "none", opacity: 0, zIndex: 3, overflow: "hidden" }}>
      <svg width="100%" height="100%" style={{ position: "absolute", inset: 0 }}>
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
          style={{ position: "absolute", left: 0, top: 0, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", lineHeight: 1.15, willChange: "transform" }}
        >
          <div style={{ font: "600 14px/1.2 var(--font-sans, system-ui, sans-serif)", color: props.color, overflow: "hidden", textOverflow: "ellipsis" }}>
            {r.title}
            {r.detail && <span style={{ fontWeight: 500, color: props.muted, marginLeft: 8 }}>{r.detail}</span>}
          </div>
          <div style={{ font: "400 11.5px/1.3 var(--font-sans, system-ui, sans-serif)", color: r.generated ? props.accent : props.muted }}>{r.sub}</div>
        </div>
      ))}
    </div>
  );
}

const tmp = new THREE.Vector3();

/** Inside the Canvas: projects anchors and lays the label column out each frame. */
export function LabelProjector() {
  const { camera, size } = useThree();
  useFrame(() => {
    const el = overlayEl;
    if (!el) return;
    const alpha = labelOpacity(stage.explode);
    el.style.opacity = String(alpha);
    if (alpha <= 0) return;
    const w = size.width;
    const h = size.height;
    const pts: { key: string; x: number; y: number }[] = [];
    for (const [key, list] of stage.anchors) {
      if (!list.length || !slots.has(key)) continue;
      tmp.copy(list[0].world()).project(camera);
      pts.push({ key, x: ((tmp.x + 1) / 2) * w, y: ((1 - tmp.y) / 2) * h });
    }
    pts.sort((a, b) => a.y - b.y);
    const maxX = pts.reduce((m, p) => Math.max(m, p.x), 0);
    const colX = Math.min(Math.max(maxX + 48, w * 0.5), w - 300);
    const top = Math.max(16, h * 0.27);
    const bottom = Math.min(h - 40, h - 150);
    const n = pts.length;
    const step = n > 1 ? Math.min(54, (bottom - top) / (n - 1)) : 0;
    const mid = pts.length ? pts.reduce((s, p) => s + p.y, 0) / n : h / 2;
    const start = Math.min(Math.max(top, mid - (step * (n - 1)) / 2), Math.max(top, bottom - step * (n - 1)));
    pts.forEach((p, i) => {
      const s = slots.get(p.key);
      if (!s) return;
      const y = start + i * step;
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
  });
  return null;
}
