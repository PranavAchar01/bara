// What you can do with the part you picked, in one small pill above the prompt: its name, then swap,
// colour, move, remove, ask, and "more" (pull it out, its details, build something around it). Nothing
// else appears until asked for: details open in the side panel, answers come back as one line from Bara.
import { useEffect, useRef, useState } from "react";
import { focusPart, select, useApp } from "../state/store";
import { applyEdit } from "../net/client";
import type { Build, BuildPart } from "../spec/types";
import { focusKeyOf } from "../three/Viewport3D";
import { Glyph, type GlyphName } from "../ui/glyphs";
import { ColorPicker } from "./Overlays";

/** The parts the pill acts on: everything pulled out together, or the one selected. */
function picked(build: Build | null, focusKey: string | null, selection: string | null): BuildPart[] {
  if (!build) return [];
  if (focusKey) return build.parts.filter((p) => focusKeyOf(build, p) === focusKey);
  const one = build.parts.find((p) => p.instance_id === selection);
  return one ? [one] : [];
}

function Act(props: { icon: GlyphName; label: string; onClick: () => void; on?: boolean; danger?: boolean; disabled?: boolean }) {
  return (
    <button
      type="button"
      className={`sb-act ${props.on ? "on" : ""} ${props.danger ? "danger" : ""}`}
      onClick={props.onClick}
      disabled={props.disabled}
      title={props.label}
      aria-label={props.label}
      aria-pressed={props.on}
    >
      <Glyph name={props.icon} />
    </button>
  );
}

export function SelectionBar() {
  const build = useApp((s) => s.build);
  const focusKey = useApp((s) => s.focusKey);
  const selection = useApp((s) => s.selection);
  const moving = useApp((s) => s.moving);
  const done = build?.status === "done";
  const parts = picked(build, focusKey, selection);
  const [colour, setColour] = useState(false);
  const [more, setMore] = useState(false);
  const [sure, setSure] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const key = parts[0]?.instance_id ?? "";
  useEffect(() => {
    setColour(false);
    setMore(false);
    setSure(false);
  }, [key, focusKey]);
  useEffect(() => {
    if (!colour && !more) return;
    const close = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) {
        setColour(false);
        setMore(false);
      }
    };
    // Esc folds a menu first, before it steps back out of the part
    const esc = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.stopImmediatePropagation();
      setColour(false);
      setMore(false);
    };
    window.addEventListener("mousedown", close);
    window.addEventListener("keydown", esc, true);
    return () => {
      window.removeEventListener("mousedown", close);
      window.removeEventListener("keydown", esc, true);
    };
  }, [colour, more]);
  if (!done || !build || !parts.length) return null;

  const first = parts[0];
  const count = parts.reduce((n, p) => n + (p.quantity || 1), 0);
  const swap = () => useApp.setState({ selection: first.instance_id, overlay: "swap" });
  const move = () => useApp.setState((s) => ({ moving: s.moving === first.instance_id ? null : first.instance_id }));
  const remove = () => {
    if (!sure) {
      setSure(true);
      return;
    }
    applyEdit(
      parts.map((p) => ({ op: "remove_part" as const, instance_id: p.instance_id })),
      `Remove ${first.card.display_name}`,
    );
    focusPart(null);
    select(null);
  };
  const ask = () => window.dispatchEvent(new Event("bara:focus-ask"));
  const details = () => {
    setMore(false);
    useApp.setState((s) => ({ selection: first.instance_id, overlay: focusKey ? "focus" : "inspector", panels: { ...s.panels, details: true } }));
  };
  const around = () => {
    setMore(false);
    window.dispatchEvent(new CustomEvent("bara:prefill", { detail: `Build around the ${first.card.display_name}: ` }));
  };
  const pull = () => {
    setMore(false);
    focusPart(focusKey ? null : focusKeyOf(build, first));
  };
  const close = () => {
    focusPart(null);
    select(null);
  };

  return (
    <div className="selection-bar" ref={box} role="toolbar" aria-label={`${first.card.display_name} actions`}>
      <button type="button" className="sb-back" onClick={close} title="Back to the whole build (Esc)" aria-label="Back to the whole build">
        <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
          <path d="M9.5 3.5 5 8l4.5 4.5" />
        </svg>
      </button>
      <span className="sb-name" title={first.card.display_name}>
        {first.card.display_name}
        {count > 1 && <span className="sb-count mono">×{count}</span>}
      </span>
      <span className="sb-sep" aria-hidden />
      <Act icon="swap" label="Swap for another part" onClick={swap} disabled={!first.slot_id} />
      <Act icon="colour" label="Colour" onClick={() => { setMore(false); setColour((c) => !c); }} on={colour} />
      <Act icon="move" label="Move" onClick={move} on={moving === first.instance_id} />
      <Act icon="ask" label="Ask or change it in words" onClick={ask} />
      <Act icon="remove" label={sure ? "Click again to remove" : "Remove"} onClick={remove} danger={sure} on={sure} />
      <Act icon="more" label="More" onClick={() => { setColour(false); setMore((m) => !m); }} on={more} />
      {colour && (
        <div className="sb-pop">
          <ColorPicker target={{ instance_id: first.instance_id }} current={first.color ?? null} onClose={() => setColour(false)} />
        </div>
      )}
      {more && (
        <div className="sb-pop sb-menu" role="menu">
          <button type="button" role="menuitem" onClick={pull}>
            <Glyph name="pull" /> {focusKey ? "Put it back" : "Pull it out"}
          </button>
          <button type="button" role="menuitem" onClick={details}>
            <Glyph name="details" /> Details
          </button>
          <button type="button" role="menuitem" onClick={around}>
            <Glyph name="around" /> Build around it
          </button>
        </div>
      )}
    </div>
  );
}

/** Bara's last short reply, above the prompt; it fades on its own and on the next one. */
export function SaysLine() {
  const says = useApp((s) => s.baraSays);
  const [shown, setShown] = useState<number | null>(null);
  useEffect(() => {
    if (!says) return;
    setShown(says.n);
    const t = window.setTimeout(() => setShown((n) => (n === says.n ? null : n)), 6500);
    return () => window.clearTimeout(t);
  }, [says]);
  if (!says || shown !== says.n) return null;
  return (
    <div className="says-line" role="status" aria-live="polite">
      <span className="says-eyes" aria-hidden>
        <i />
        <i />
      </span>
      {says.text}
    </div>
  );
}
