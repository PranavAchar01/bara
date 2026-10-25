import { useEffect, useRef, useState, type FormEvent } from "react";
import { ShoppingListButton } from "./ShoppingList";
import { useApp } from "../state/store";
import { paths } from "../net/rest";
import { serverUrl, storeKey } from "../net/mode";
import { Icon } from "../ui/common";
import type { ConnStatus } from "../net/connection";
import { SimulateButton } from "../sim/SimulateButton";
import { useLibrary } from "../library/library";
import { BaraMark } from "./Handoff";
import { openBuildDialog } from "./BuildDialog";
import { useCombinedTitle } from "../project/scenes";

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
  const combined = useCombinedTitle(build?.build_id);
  return (
    <header className="topbar">
      <button type="button" className="brand" onClick={() => useApp.setState({ screen: "home" })} title="Home">
        <BaraMark className="brand-mark" />
        <span>Bara</span>
        {screen !== "workspace" && <span className="brand-by">by Tangible Parts</span>}
      </button>
      {screen === "home" && <LandingNav />}
      {screen === "workspace" && build && (
        <div className="topbar-build">
          <span className="mono muted">{build.build_id}</span>
          <span className={`status-pill st-${String(status)}`}>{String(status).replace("_", " ")}</span>
          <span className="topbar-prompt" title={build.prompt}>
            {combined ?? build.prompt}
          </span>
        </div>
      )}
      <div className="topbar-right">
        {screen === "workspace" && (mock || hello?.mock) && <span className="badge tone-info">mock</span>}
        {/* Which model answers is a detail for the hover, not a label on the page. */}
        <span
          className={`conn-pill tone-${CONN_TONE[conn]}`}
          aria-live="polite"
          title={health?.llm?.provider ? `${health.llm.provider} ${health.llm.model}. Fallback: ${health.llm_fallback?.provider ?? "none"} ${health.llm_fallback?.model ?? ""}` : undefined}
        >
          <span className="dot" />
          {CONN_LABEL[conn]}
        </span>
        {screen === "workspace" && (
          <button type="button" className="btn ghost sm" onClick={() => useApp.setState({ screen: "home" })}>
            <Icon name="home" /> Home
          </button>
        )}
        {screen === "workspace" && <ShoppingListButton />}
        <ExportMenu />
        {screen === "home" && (
          <button type="button" className="btn primary sm nav-build" onClick={() => openBuildDialog()} aria-haspopup="dialog">
            Start building
          </button>
        )}
        {screen !== "workspace" && <DraftsButton />}
      </div>
    </header>
  );
}

const NAV: { id: string; label: string }[] = [
  { id: "how", label: "How it works" },
  { id: "examples", label: "Examples" },
  { id: "faq", label: "FAQ" },
];

/** Anchor links to the landing's sections; the page scrolls inside its own container. */
function LandingNav() {
  return (
    <nav className="ld-nav" aria-label="On this page">
      {NAV.map((n) => (
        <a
          key={n.id}
          href={`#${n.id}`}
          onClick={(e) => {
            e.preventDefault();
            document.getElementById(n.id)?.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
          }}
        >
          {n.label}
        </a>
      ))}
    </nav>
  );
}

/** Top right of Home: opens the Library page (finished builds plus this browser's drafts); on Library it goes back. */
function DraftsButton() {
  const screen = useApp((s) => s.screen);
  const count = useLibrary((s) => s.cards.length);
  const on = screen === "drafts";
  return (
    <button
      type="button"
      className={`btn sm drafts-btn ${on ? "on" : ""}`}
      aria-current={on ? "page" : undefined}
      onClick={() => useApp.setState({ screen: on ? "home" : "drafts" })}
    >
      Library
      {count > 0 && <span className="drafts-n mono">{count}</span>}
    </button>
  );
}

/** Left panel header in the workspace (Figma file header): Builds / prompt, then a status dot and Replay. */
export function FileHeader() {
  const conn = useApp((s) => s.conn);
  const hello = useApp((s) => s.hello);
  const build = useApp((s) => s.build);
  const health = useApp((s) => s.health);
  const mock = useApp((s) => s.mode.mock);
  const status = build?.status ?? "idle";
  const combined = useCombinedTitle(build?.build_id);
  const fallback = health?.llm_fallback?.provider ? `Fallback: ${health.llm_fallback.provider} ${health.llm_fallback.model ?? ""}` : "No fallback";
  const used = usedModels(build);
  const primary = health?.llm?.model;
  // The build used something other than the configured model: say which, and why, instead of switching silently.
  const switched = used.backup || (primary !== undefined && used.models.some((m) => m !== primary));
  const usedName = used.models.find((m) => m !== primary) ?? (used.backup ? "rules only" : primary);
  const why = used.reasons[0] ?? (used.backup ? "The primary model failed, so the backup answered." : "This build used a different model.");
  return (
    <header className="file-header">
      <div className="file-title">
        <button type="button" className="brand" onClick={() => useApp.setState({ screen: "home" })} title="Home">
          Builds
        </button>
        <span className="sep">/</span>
        <span className="file-prompt" title={build?.prompt}>
          {combined ?? build?.prompt ?? "New build"}
        </span>
      </div>
      <div className="file-meta">
        {/* One dot says it all: green connected, amber when the build fell back to another model, red offline. Details on hover. */}
        <span
          className={`conn-dot tone-${switched && conn === "open" ? "warn" : CONN_TONE[conn]}`}
          role="img"
          aria-label={CONN_LABEL[conn]}
          title={[
            `${CONN_LABEL[conn]}${build ? ` · ${build.build_id} · ${String(status).replace("_", " ")}` : ""}`,
            health?.llm?.model ? (switched ? `${why} Used ${usedName} instead of ${health.llm.model}.` : `${health.llm.provider} ${health.llm.model}. ${fallback}`) : "",
          ]
            .filter(Boolean)
            .join("\n")}
        />
        {conn !== "open" && <span aria-live="polite">{CONN_LABEL[conn]}</span>}
        {(mock || hello?.mock) && <span className="status-pill">mock</span>}
      </div>
    </header>
  );
}

/** Models this build's calls went to, whether any of them was the backup, and the warnings that explain it. */
function usedModels(build: ReturnType<typeof useApp.getState>["build"]) {
  const calls = [build?.spec?.classifier, ...(build?.decisions ?? []).map((d) => d.model)].filter((c) => c != null);
  const models = [...new Set(calls.map((c) => c.model).filter((m): m is string => !!m))];
  const backup = calls.some((c) => c.fallback);
  const reasons = (build?.warnings ?? []).filter((w) => w.code === "llm_fallback" || w.code === "llm_degraded").map((w) => w.message);
  return { models, backup, reasons };
}

/** Right panel header in the workspace (Figma toolbar right): Home and Export, Export is the one primary action. */
export function PanelToolbar() {
  return (
    <div className="panel-toolbar">
      <button type="button" className="btn ghost sm icon" onClick={() => useApp.setState({ screen: "home" })} title="Home">
        <Icon name="home" />
      </button>
      <span className="spacer" />
      <SimulateButton />
      <ShoppingListButton compact />
      <ExportMenu primary />
    </div>
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
export function ExportMenu(props: { primary?: boolean }) {
  const build = useApp((s) => s.build);
  const compiling = useApp((s) => s.view.firmwareProgress !== null || s.build?.firmware?.compile.status === "running");
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
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
  const ready = build?.status === "done";
  return (
    <div className="menu" ref={ref}>
      <button
        type="button"
        className={`btn sm ${props.primary ? "primary" : ""}`}
        disabled={!ready}
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        title={ready ? "Export" : "Export unlocks when the build is done"}
      >
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
              <a key={f.id} className="menu-item" role="menuitem" href={serverUrl(paths.export(build.build_id, f.id))} download onClick={() => setOpen(false)}>
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
        ? "Can't reach the build engine. Trying again every 8 s; what's on screen stays, and your saved builds still open."
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

/** Engine reachability for the deployed site: says plainly when it shows the demo instead of the engine. */
export function EngineNotice() {
  const engine = useApp((s) => s.engine);
  const detail = useApp((s) => s.engineDetail);
  const [key, setKey] = useState("");
  if (engine === "local" || engine === "live") return null;
  if (engine === "checking") {
    return (
      <div className="conn-banner tone-info" role="status">
        <span className="spinner" aria-hidden />
        Looking for the engine.
      </div>
    );
  }
  const unlock = (e: FormEvent) => {
    e.preventDefault();
    if (!key.trim()) return;
    storeKey(key.trim());
    window.location.reload();
  };
  return (
    <div className={`conn-banner engine-notice tone-${engine === "locked" ? "warn" : "fail"}`} role="status">
      <strong>{engine === "locked" ? "Engine locked." : "Engine offline."}</strong>
      <span>{detail} Builds here are the recorded demo, not your engine.</span>
      {engine === "locked" ? (
        <form className="engine-key" onSubmit={unlock}>
          <input
            type="password"
            className="engine-key-input"
            placeholder="Access key"
            autoComplete="current-password"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            aria-label="Access key"
          />
          <button type="submit" className="btn sm primary">
            Unlock
          </button>
        </form>
      ) : (
        <button type="button" className="btn sm" onClick={() => window.location.reload()}>
          Retry
        </button>
      )}
    </div>
  );
}
