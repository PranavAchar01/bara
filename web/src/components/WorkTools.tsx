// The few controls along the top of the canvas, right of the device tabs: undo, redo and the versions
// list; the two side panels (both closed until asked for); simulate and export. Everything else waits
// in the panels, so the canvas stays the device and nothing else.
import { useEffect, useRef, useState } from "react";
import { useApp } from "../state/store";
import { restoreRevision } from "../net/client";
import { Glyph } from "../ui/glyphs";
import { ExportMenu } from "./TopBar";
import { SimulateButton } from "../sim/SimulateButton";

function inField(t: EventTarget | null): boolean {
  const el = t as HTMLElement | null;
  return !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable);
}

const NO_HISTORY: [] = [];

/** Undo, redo and every version of the build: each one can be brought back (it becomes the newest). */
export function HistoryControls() {
  const history = useApp((s) => s.view.history ?? NO_HISTORY);
  const at = useApp((s) => s.view.historyAt ?? -1);
  const done = useApp((s) => s.build?.status === "done");
  const editing = useApp((s) => s.view.edit?.phase === "pending" || s.view.edit?.phase === "applying");
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const ready = done && !busy && !editing;
  const go = async (i: number) => {
    const v = history[i];
    if (!v || i === at || !ready) return;
    setBusy(true);
    await restoreRevision(v.revision);
    setBusy(false);
  };
  const undo = () => void go(at - 1);
  const redo = () => void go(at + 1);
  const goRef = useRef({ undo, redo });
  goRef.current = { undo, redo };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey) || e.key.toLowerCase() !== "z" || inField(e.target)) return;
      e.preventDefault();
      if (e.shiftKey) goRef.current.redo();
      else goRef.current.undo();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    const esc = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.stopImmediatePropagation();
      setOpen(false);
    };
    window.addEventListener("mousedown", close);
    window.addEventListener("keydown", esc, true);
    return () => {
      window.removeEventListener("mousedown", close);
      window.removeEventListener("keydown", esc, true);
    };
  }, [open]);

  const hasPast = history.length > 1;
  return (
    <div className="wt-history" ref={box}>
      <button type="button" className="wt-btn" onClick={undo} disabled={!ready || at <= 0} title="Undo (⌘Z)" aria-label="Undo">
        <Glyph name="undo" />
      </button>
      <button type="button" className="wt-btn" onClick={redo} disabled={!ready || at < 0 || at >= history.length - 1} title="Redo (⇧⌘Z)" aria-label="Redo">
        <Glyph name="redo" />
      </button>
      <button type="button" className={`wt-btn ${open ? "on" : ""}`} onClick={() => setOpen((o) => !o)} disabled={!hasPast} title="Versions" aria-label="Versions" aria-expanded={open}>
        <Glyph name="versions" />
      </button>
      {open && hasPast && (
        <ol className="wt-versions" aria-label="Versions">
          {history
            .map((v, i) => ({ v, i }))
            .reverse()
            .map(({ v, i }) => (
              <li key={`${v.revision}-${i}`}>
                <button type="button" className={i === at ? "now" : ""} onClick={() => void go(i)} disabled={!ready || i === at}>
                  <span className="wt-dot" aria-hidden />
                  <span className="wt-label">{v.label}</span>
                  {i === at && <span className="wt-now mono">now</span>}
                </button>
              </li>
            ))}
        </ol>
      )}
    </div>
  );
}

/** Right of the tabs: history, the two panel toggles, simulate and export. */
/** One click pulls the device apart into its exploded view; again puts it back together. */
function ExplodeButton() {
  const open = useApp((s) => s.explode > 0.5);
  return (
    <button
      type="button"
      className={`btn sm ${open ? "on" : ""}`}
      aria-pressed={open}
      onClick={() => useApp.setState({ explode: open ? 0 : 1 })}
      title={open ? "Put it back together" : "Pull it apart to see every part"}
    >
      {open ? "Assemble" : "Explode"}
    </button>
  );
}

export function WorkTools() {
  const panels = useApp((s) => s.panels);
  const hasBuild = useApp((s) => s.build !== null);
  const toggle = (k: "layers" | "details") => useApp.setState((s) => ({ panels: { ...s.panels, [k]: !s.panels[k] } }));
  return (
    <div className="wt">
      {hasBuild && <HistoryControls />}
      {hasBuild && (
        <>
          <span className="wt-sep" aria-hidden />
          <button type="button" className={`wt-btn ${panels.layers ? "on" : ""}`} aria-pressed={panels.layers} onClick={() => toggle("layers")} title="Parts" aria-label="Parts">
            <Glyph name="layers" />
          </button>
          <button type="button" className={`wt-btn ${panels.details ? "on" : ""}`} aria-pressed={panels.details} onClick={() => toggle("details")} title="Details" aria-label="Details">
            <Glyph name="details" />
          </button>
          <span className="wt-sep" aria-hidden />
          <ExplodeButton />
          <SimulateButton />
          <ExportMenu primary />
        </>
      )}
    </div>
  );
}
