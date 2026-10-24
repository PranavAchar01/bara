// Hover a part (in the viewport or the parts list) and, after a short beat,
// the bot flies over, points at it and says why it was picked. A small card
// beside the bot holds the longer facts. With the agent turned off (?agent=0)
// only the card shows, next to the pointer.
import { useEffect, useMemo, useRef, useState } from "react";
import { useApp } from "../state/store";
import { agentEnabled, type Rect } from "./agent";
import { agentDo, agentPos } from "./agentBus";
import { explainPart, partName, type PartExplanation } from "./explain";

const HOVER_MS = 450;
const REFIRE_AFTER_MS = 1000;
const DWELL_MS = 2600;
const GAP = 14;
const MARGIN = 8;
const LABEL_MAX = 31;

function rowId(el: EventTarget | null): string | null {
  if (!(el instanceof Element)) return null;
  const row = el.closest('[data-agent^="row:"]');
  return row ? (row.getAttribute("data-agent") ?? "").slice(4) || null : null;
}

/** The parts list rows count as hovering the part. */
function useRowHover(): string | null {
  const [id, setId] = useState<string | null>(null);
  useEffect(() => {
    const over = (e: PointerEvent) => {
      const r = rowId(e.target);
      if (r) setId(r);
    };
    const out = (e: PointerEvent) => {
      const from = rowId(e.target);
      if (!from) return;
      if (rowId(e.relatedTarget) === from) return;
      setId(null);
    };
    document.addEventListener("pointerover", over);
    document.addEventListener("pointerout", out);
    return () => {
      document.removeEventListener("pointerover", over);
      document.removeEventListener("pointerout", out);
    };
  }, []);
  return id;
}

export function Explainer() {
  const enabled = useMemo(agentEnabled, []);
  const viewportHover = useApp((s) => s.hoverPart);
  const rowHover = useRowHover();
  const hovered = rowHover ?? viewportHover;

  const [shown, setShown] = useState<PartExplanation | null>(null);
  const [visible, setVisible] = useState(false);
  const cardRef = useRef<HTMLDivElement>(null);
  const pointer = useRef({ x: 0, y: 0 });
  const lastFired = useRef<{ id: string; leftAt: number | null } | null>(null);

  // Pointer position, for the card when the bot is not out (or turned off).
  useEffect(() => {
    const move = (e: PointerEvent) => {
      pointer.current = { x: e.clientX, y: e.clientY };
    };
    document.addEventListener("pointermove", move, { passive: true });
    return () => document.removeEventListener("pointermove", move);
  }, []);

  // Hover settles for HOVER_MS -> explain. Leaving starts the re-fire clock.
  useEffect(() => {
    if (!hovered) {
      setVisible(false);
      if (lastFired.current && lastFired.current.leftAt == null) lastFired.current.leftAt = Date.now();
      return;
    }
    const t = window.setTimeout(() => {
      const s = useApp.getState();
      if (s.replaying || s.build?.status === "running") return;
      const e = explainPart(s.build, s.view, hovered);
      if (!e) return;
      setShown(e);
      setVisible(true);
      const prev = lastFired.current;
      const now = Date.now();
      const recent = prev?.id === hovered && (prev.leftAt == null || now - prev.leftAt <= REFIRE_AFTER_MS);
      lastFired.current = { id: hovered, leftAt: null };
      if (recent || !enabled) return;
      const part = s.build?.parts.find((p) => p.instance_id === hovered);
      let label = part ? partName(part) : hovered;
      if (label.length > LABEL_MAX) label = label.slice(0, LABEL_MAX - 1).trimEnd() + "…";
      agentDo({
        source: "explain",
        interrupt: true,
        say: e.short,
        beats: [{ id: `explain:${hovered}:${now}`, target: { kind: "part", id: hovered }, action: "look", label, dwellMs: DWELL_MS }],
      });
    }, HOVER_MS);
    return () => {
      window.clearTimeout(t);
      // Moving straight from one part to another counts as leaving the first.
      if (lastFired.current && lastFired.current.id === hovered && lastFired.current.leftAt == null) {
        lastFired.current.leftAt = Date.now();
      }
    };
  }, [hovered, enabled]);

  // Follow the bot (or the pointer) every frame while the card is up.
  useEffect(() => {
    if (!visible) return;
    let raf = 0;
    const tick = () => {
      const el = cardRef.current;
      if (el) {
        const bot: Rect | null = enabled ? agentPos() : null;
        const anchor: Rect = bot ?? { x: pointer.current.x, y: pointer.current.y, w: 0, h: 0 };
        const w = el.offsetWidth;
        const h = el.offsetHeight;
        const vw = window.innerWidth;
        const vh = window.innerHeight;
        // Under the bot, so its speech bubble (beside and above it) stays readable;
        // beside it on the left when there is no room below.
        let x = bot ? anchor.x : anchor.x + GAP;
        let y = anchor.y + anchor.h + GAP;
        if (bot && y + h > vh - MARGIN) {
          x = anchor.x - GAP - w;
          y = anchor.y + anchor.h / 2 - h / 2;
        }
        x = Math.max(MARGIN, Math.min(x, vw - w - MARGIN));
        y = Math.max(MARGIN, Math.min(y, vh - h - MARGIN));
        el.style.transform = `translate(${Math.round(x)}px, ${Math.round(y)}px)`;
      }
      raf = requestAnimationFrame(tick);
    };
    tick();
    return () => cancelAnimationFrame(raf);
  }, [visible, enabled]);

  if (!shown) return null;
  return (
    <div
      ref={cardRef}
      aria-hidden={!visible}
      role="status"
      style={{
        position: "fixed",
        left: 0,
        top: 0,
        zIndex: 56,
        width: "max-content",
        maxWidth: 280,
        padding: "10px 12px",
        background: "var(--surface)",
        color: "var(--text)",
        border: "1px solid var(--line)",
        borderRadius: "var(--radius)",
        boxShadow: "var(--shadow-pop)",
        font: "13px/1.4 var(--font-sans)",
        letterSpacing: "var(--track-body)",
        pointerEvents: "none",
        opacity: visible ? 1 : 0,
        transition: visible ? "opacity 160ms ease-out" : "opacity 220ms ease-in",
      }}
    >
      {!enabled && <div style={{ fontWeight: 600, marginBottom: 4 }}>{shown.short}</div>}
      <ul style={{ margin: 0, paddingLeft: 16, color: "var(--text-2)" }}>
        {shown.long.map((l, i) => (
          <li key={i} style={{ marginTop: i ? 3 : 0 }}>
            {l}
          </li>
        ))}
      </ul>
    </div>
  );
}
