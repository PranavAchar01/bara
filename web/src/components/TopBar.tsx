import { useEffect, useRef, useState } from "react";
import { useApp } from "../state/store";
import { paths } from "../net/rest";
import { Icon } from "../ui/common";
import type { ConnStatus } from "../net/connection";

const CONN_LABEL: Record<ConnStatus, string> = {
  connecting: "Connecting",
  open: "Connected",
  reconnecting: "Reconnecting",
  resyncing: "Resyncing",
  offline: "Offline",
};

const CONN_TONE: Record<ConnStatus, string> = {
  connecting: "info",
  open: "ok",
  reconnecting: "warn",
  resyncing: "warn",
  offline: "fail",
};

/** C01 TopBar. */
export function TopBar() {
  const conn = useApp((s) => s.conn);
  const hello = useApp((s) => s.hello);
  const build = useApp((s) => s.build);
  const screen = useApp((s) => s.screen);
  const health = useApp((s) => s.health);
  const mock = useApp((s) => s.mode.mock);
  const status = build?.status ?? "idle";
  return (
    <header className="topbar">
      <button type="button" className="brand" onClick={() => useApp.setState({ screen: "home" })} title="Home">
        <BaraMark />
        <span>Bara</span>
      </button>
      {screen === "workspace" && build && (
        <div className="topbar-build">
          <span className="mono muted">{build.build_id}</span>
          <span className={`status-pill st-${String(status)}`}>{String(status).replace("_", " ")}</span>
          <span className="topbar-prompt" title={build.prompt}>
            {build.prompt}
          </span>
        </div>
      )}
      <div className="topbar-right">
        {(mock || hello?.mock) && <span className="badge tone-info">mock</span>}
        {health?.llm?.provider && (
          <span className="muted small" title={`Fallback: ${health.llm_fallback?.provider ?? "none"} ${health.llm_fallback?.model ?? ""}`}>
            {health.llm.provider} {health.llm.model}
          </span>
        )}
        <span className={`conn-pill tone-${CONN_TONE[conn]}`} aria-live="polite">
          <span className="dot" />
          {CONN_LABEL[conn]}
        </span>
        {screen === "workspace" && (
          <button type="button" className="btn ghost sm" onClick={() => useApp.setState({ screen: "home" })}>
            <Icon name="home" /> Home
          </button>
        )}
        <ExportMenu />
      </div>
    </header>
  );
}

function BaraMark() {
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" aria-hidden>
      <rect x="1.5" y="1.5" width="17" height="17" rx="3.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
      <rect x="5" y="5" width="4" height="4" rx="0.8" fill="var(--accent)" />
      <rect x="11" y="5" width="4" height="4" rx="0.8" fill="currentColor" opacity="0.5" />
      <rect x="5" y="11" width="10" height="4" rx="0.8" fill="currentColor" opacity="0.5" />
    </svg>
  );
}

const FORMATS: { id: string; label: string }[] = [
  { id: "bom_csv", label: "BOM (CSV)" },
  { id: "stl", label: "STL" },
  { id: "3mf", label: "3MF" },
  { id: "step", label: "STEP" },
  { id: "kicad", label: "KiCad" },
  { id: "firmware_zip", label: "Firmware (zip)" },
  { id: "zip", label: "Everything (zip)" },
];

/** C24 ExportMenu: disabled until build.done. */
export function ExportMenu() {
  const build = useApp((s) => s.build);
  const compiling = useApp((s) => s.view.firmwareProgress !== null || s.build?.firmware?.compile.status === "running");
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("mousedown", close);
    return () => window.removeEventListener("mousedown", close);
  }, [open]);
  const ready = build?.status === "done";
  return (
    <div className="menu" ref={ref}>
      <button type="button" className="btn sm" disabled={!ready} onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <Icon name="export" /> Export
      </button>
      {open && ready && build && (
        <div className="menu-list" role="menu">
          {FORMATS.map((f) => {
            const disabled = f.id === "firmware_zip" && compiling;
            return disabled ? (
              <span key={f.id} className="menu-item disabled" title="Firmware is still compiling">
                {f.label}
              </span>
            ) : (
              <a key={f.id} className="menu-item" role="menuitem" href={paths.export(build.build_id, f.id)} download onClick={() => setOpen(false)}>
                {f.label}
              </a>
            );
          })}
        </div>
      )}
    </div>
  );
}

/** C26 ConnectionBanner (the socket logic lives in net/connection.ts). */
export function ConnectionBanner() {
  const conn = useApp((s) => s.conn);
  const hasBuild = useApp((s) => s.build !== null);
  if (conn === "open" || (conn === "connecting" && !hasBuild)) return null;
  const text =
    conn === "resyncing"
      ? "Reconnected. Catching up on missed events; editing is paused."
      : conn === "offline"
        ? "Offline. Still retrying every 8 s; the last state stays on screen."
        : conn === "connecting"
          ? "Connecting to the build server."
          : "Connection lost. Reconnecting; the last state stays on screen.";
  return (
    <div className={`conn-banner tone-${conn === "offline" ? "fail" : "warn"}`} role="status">
      <span className="spinner" aria-hidden />
      {text}
    </div>
  );
}
