// The strip along the top of the canvas: Bara (home) and the live dot on the left, then one tab per
// canvas (click to switch, double-click to rename, x to close) and "New canvas" for an empty one, and
// the workspace tools on the right (WorkTools). A device made for another ("add a mouse to this
// keyboard") opens as a tab right after its parent's, marked as pairing with it.
import { useEffect, useRef, useState } from "react";
import { useApp, type CanvasMeta } from "../state/store";
import { addCanvas, canvasLabel, canvasState, canvasStatus, renameCanvas, switchCanvas, type CanvasStatus } from "../state/canvases";
import { closeCanvasTab } from "../net/client";
import { Icon } from "../ui/common";
import "./canvasTabs.css";
import { ReplayControl } from "../bot/ReplayControl";
import { WorkTools } from "./WorkTools";
import { Glyph } from "../ui/glyphs";
import { SPEEDS, canReplay, setReplaySpeed, startReplay, stopReplay, useReplay } from "../bot/replay";
import { setProjectOpen, useProject, useProjectDevices } from "../project/project";
import { ProjectButton } from "../project/ProjectPanel";
import { useTabTitle } from "../project/scenes";

const STATUS_TITLE: Record<CanvasStatus, string> = {
  empty: "Empty",
  starting: "Starting",
  restoring: "Loading the build again",
  running: "Building",
  awaiting_input: "Waiting for your answer",
  done: "Done",
  failed: "Failed",
  cancelled: "Cancelled",
};

/** Closes a small menu on an outside press or Esc. */
function useDismiss(open: boolean, close: () => void, box: React.RefObject<HTMLElement>) {
  useEffect(() => {
    if (!open) return;
    const down = (e: PointerEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) close();
    };
    const esc = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.stopImmediatePropagation();
      close();
    };
    window.addEventListener("pointerdown", down, true);
    window.addEventListener("keydown", esc, true);
    return () => {
      window.removeEventListener("pointerdown", down, true);
      window.removeEventListener("keydown", esc, true);
    };
  }, [open, close, box]);
}

export function CanvasTabs() {
  const conn = useApp((s) => s.conn);
  const replaying = useApp((s) => s.replaying);
  const canvases = useApp((s) => s.canvases);
  const active = useApp((s) => s.activeCanvas);
  return (
    <nav className="canvas-tabs" aria-label="Canvases">
      <button type="button" className="ct-home" onClick={() => useApp.setState({ screen: "home" })} title="Home">
        Bara
        <span className={`ct-conn ${conn === "open" ? "ok" : conn === "offline" ? "off" : "wait"}`} title={conn === "open" ? "Connected" : conn} aria-hidden />
      </button>
      <div className="ct-list" role="tablist">
        {canvases.map((m) => (
          <CanvasTab key={m.id} meta={m} active={m.id === active} lone={canvases.length === 1} />
        ))}
      </div>
      <button
        type="button"
        className="ct-add ct-add-new"
        data-agent="new-canvas"
        onClick={() => {
          // a replay re-performs this canvas's build; stop it so the real one is what gets stashed
          stopReplay();
          addCanvas();
        }}
        title="New canvas"
      >
        <svg width="12" height="12" viewBox="0 0 16 16" aria-hidden>
          <path d="M8 3v10M3 8h10" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
        </svg>
        <span>New canvas</span>
      </button>
      <span className="ct-spacer" />
      <ProjectWhenMany />
      {replaying && <ReplayControl />}
      <WorkTools />
      <MoreMenu />
    </nav>
  );
}

function CanvasTab(props: { meta: CanvasMeta; active: boolean; lone: boolean }) {
  const { meta, active } = props;
  const status = useApp((s) => canvasStatus(s, meta.id));
  const label = useApp((s) => canvasLabel(meta, canvasState(s, meta.id)));
  const parent = useApp((s) => {
    const p = meta.pairsWith ? s.canvases.find((c) => c.id === meta.pairsWith) : undefined;
    return p ? canvasLabel(p, canvasState(s, p.id)) : null;
  });
  const combined = useTabTitle(useApp((s) => canvasState(s, meta.id)?.build?.build_id));
  const [editing, setEditing] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (editing) input.current?.select();
  }, [editing]);
  const live = status === "running" || status === "awaiting_input" || status === "starting";
  const commit = (v: string | null) => {
    if (v !== null) renameCanvas(meta.id, v);
    setEditing(false);
  };
  const name = combined ?? label;
  return (
    <div className={`ct-tab ${active ? "active" : ""}`} data-canvas={meta.id} data-kind={meta.kind ?? undefined} title={`${name}${parent ? `, pairs with ${parent}` : ""} · ${STATUS_TITLE[status]}`}>
      <span className={`ct-dot st-${status}`} aria-label={STATUS_TITLE[status]} />
      {editing ? (
        <input
          ref={input}
          className="ct-name-input"
          defaultValue={meta.name ?? label}
          aria-label="Canvas name"
          onBlur={(e) => commit(e.currentTarget.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") commit(e.currentTarget.value);
            if (e.key === "Escape") {
              e.stopPropagation();
              commit(null);
            }
          }}
        />
      ) : (
        <button
          type="button"
          role="tab"
          aria-selected={active}
          className="ct-name"
          onClick={() => {
            stopReplay();
            switchCanvas(meta.id);
          }}
          onDoubleClick={() => setEditing(true)}
        >
          {name}
        </button>
      )}
      {parent && (
        <span className="ct-pair" aria-label={`Pairs with ${parent}`}>
          <svg viewBox="0 0 16 16" width="11" height="11" aria-hidden>
            <rect x="1.5" y="4.5" width="6" height="7" rx="1.6" fill="none" stroke="currentColor" strokeWidth="1.3" />
            <rect x="9.5" y="6" width="5" height="5" rx="1.6" fill="none" stroke="currentColor" strokeWidth="1.3" />
          </svg>
        </span>
      )}
      {!(props.lone && status === "empty") && (
        <button type="button" className="ct-close" onClick={() => closeCanvasTab(meta.id)} title={live ? "Close canvas (stops its build)" : "Close canvas"} aria-label={`Close ${label}`}>
          <Icon name="x" size={10} />
        </button>
      )}
    </div>
  );
}

/** The project pill earns its place in the strip once there are two devices to link. */
function ProjectWhenMany() {
  const n = useProjectDevices().length;
  return n > 1 ? <ProjectButton /> : null;
}

function MoreMenu() {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const close = useRef(() => setOpen(false)).current;
  useDismiss(open, close, box);
  const build = useApp((s) => s.build);
  const replaying = useApp((s) => s.replaying);
  const speed = useReplay((s) => s.speed);
  const loading = useReplay((s) => s.loading);
  const projectOpen = useProject((s) => s.open);
  const replayable = !replaying && canReplay(build);
  return (
    <div className="ct-tools-more" ref={box}>
      <button type="button" className={`wt-btn ${open ? "on" : ""}`} onClick={() => setOpen((o) => !o)} aria-expanded={open} aria-label="More" title="More">
        <Glyph name="more" />
      </button>
      {open && (
        <div className="ct-menu ct-menu-right" role="menu" aria-label="More">
          <button
            type="button"
            role="menuitem"
            disabled={!replayable || loading}
            onClick={() => {
              void startReplay(speed);
              close();
            }}
          >
            <Icon name="play" size={12} />
            <span className="ct-menu-name">{loading ? "Loading the replay" : "Replay the build"}</span>
            <kbd>R</kbd>
          </button>
          <div className="ct-speeds" role="group" aria-label="Replay speed">
            {SPEEDS.map((v) => (
              <button key={v} type="button" className={v === speed ? "on" : ""} onClick={() => setReplaySpeed(v)} aria-pressed={v === speed}>
                {v === 0.5 ? "½×" : `${v}×`}
              </button>
            ))}
          </div>
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setProjectOpen(!projectOpen);
              close();
            }}
          >
            <span className="ct-menu-ico" aria-hidden>
              <svg viewBox="0 0 16 16" width="12" height="12">
                <rect x="1.5" y="4" width="5" height="8" rx="1.5" fill="none" stroke="currentColor" strokeWidth="1.3" />
                <rect x="9.5" y="6" width="5" height="5" rx="1.5" fill="none" stroke="currentColor" strokeWidth="1.3" />
              </svg>
            </span>
            <span className="ct-menu-name">{projectOpen ? "Hide the project" : "Project: devices and links"}</span>
          </button>
        </div>
      )}
    </div>
  );
}
