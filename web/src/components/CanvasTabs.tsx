// The strip along the top of the canvas: Bara (home) and the live dot on the left, then one tab per
// device (several builds open at once; click to switch, double-click to rename, × to close, + for a new
// empty one), and the workspace tools on the right (WorkTools).
import { useEffect, useRef, useState } from "react";
import { useApp, type CanvasMeta } from "../state/store";
import {
  addCanvas,
  canvasLabel,
  canvasState,
  canvasStatus,
  renameCanvas,
  switchCanvas,
  type CanvasStatus,
} from "../state/canvases";
import { closeCanvasTab } from "../net/client";
import { Icon } from "../ui/common";
import "./canvasTabs.css";
import { stopReplay } from "../bot/replay";
import { ProjectButton } from "../project/ProjectPanel";
import { ReplayControl } from "../bot/ReplayControl";
import { WorkTools } from "./WorkTools";

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

export function CanvasTabs() {
  const canvases = useApp((s) => s.canvases);
  const active = useApp((s) => s.activeCanvas);
  const conn = useApp((s) => s.conn);
  return (
    <nav className="canvas-tabs" aria-label="Canvases">
      <button type="button" className="ct-home" onClick={() => useApp.setState({ screen: "home" })} title="Home">
        Bara
        <span className={`ct-conn ${conn === "open" ? "ok" : conn === "offline" ? "off" : "wait"}`} title={conn === "open" ? "Connected" : conn} aria-hidden />
      </button>
      <div className="ct-list" role="tablist">
        {canvases.map((m) => (
          <CanvasTab
            key={m.id}
            meta={m}
            active={m.id === active}
            lone={canvases.length === 1}
          />
        ))}
      </div>
      <button
        type="button"
        className="ct-add"
        onClick={() => {
          stopReplay();
          addCanvas();
        }}
        title="New canvas"
        aria-label="New canvas"
      >
        <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden>
          <path
            d="M8 3v10M3 8h10"
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinecap="round"
          />
        </svg>
      </button>
      <ProjectButton />
      <span className="ct-spacer" />
      <ReplayControl />
      <WorkTools />
    </nav>
  );
}

function CanvasTab(props: {
  meta: CanvasMeta;
  active: boolean;
  lone: boolean;
}) {
  const { meta, active } = props;
  const status = useApp((s) => canvasStatus(s, meta.id));
  const label = useApp((s) => canvasLabel(meta, canvasState(s, meta.id)));
  const [editing, setEditing] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (editing) input.current?.select();
  }, [editing]);
  const live =
    status === "running" ||
    status === "awaiting_input" ||
    status === "starting";
  const commit = (v: string | null) => {
    if (v !== null) renameCanvas(meta.id, v);
    setEditing(false);
  };
  return (
    <div
      className={`ct-tab ${active ? "active" : ""}`}
      title={`${label} · ${STATUS_TITLE[status]}`}
    >
      <span
        className={`ct-dot st-${status}`}
        aria-label={STATUS_TITLE[status]}
      />
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
            // A replay re-performs this canvas's build; stop it so the real one is what gets stashed.
            stopReplay();
            switchCanvas(meta.id);
          }}
          onDoubleClick={() => setEditing(true)}
        >
          {label}
        </button>
      )}
      {!(props.lone && status === "empty") && (
        <button
          type="button"
          className="ct-close"
          onClick={() => closeCanvasTab(meta.id)}
          title={live ? "Close canvas (stops its build)" : "Close canvas"}
          aria-label={`Close ${label}`}
        >
          <Icon name="x" size={10} />
        </button>
      )}
    </div>
  );
}
