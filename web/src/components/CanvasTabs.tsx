// The strip along the top of the canvas: Bara (home) and the live dot on the left, and the workspace
// tools on the right (WorkTools). One workspace, so there are no canvas tabs.
import { useEffect, useRef, useState } from "react";
import { useApp } from "../state/store";
import { Icon } from "../ui/common";
import "./canvasTabs.css";
import { ReplayControl } from "../bot/ReplayControl";
import { WorkTools } from "./WorkTools";
import { Glyph } from "../ui/glyphs";
import { SPEEDS, canReplay, setReplaySpeed, startReplay, useReplay } from "../bot/replay";
import { setProjectOpen, useProject, useProjectDevices } from "../project/project";
import { ProjectButton } from "../project/ProjectPanel";

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
  return (
    <nav className="canvas-tabs" aria-label="Canvases">
      <button type="button" className="ct-home" onClick={() => useApp.setState({ screen: "home" })} title="Home">
        Tangible
        <span className={`ct-conn ${conn === "open" ? "ok" : conn === "offline" ? "off" : "wait"}`} title={conn === "open" ? "Connected" : conn} aria-hidden />
      </button>
      {/* one workspace: no canvas tabs; a device added from the prompt joins this canvas */}
      <div className="ct-strip" />
      <ProjectWhenMany />
      {replaying && <ReplayControl />}
      <WorkTools />
      <MoreMenu />
    </nav>
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
