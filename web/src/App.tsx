import { useEffect } from "react";
import { useApp } from "./state/store";
import { ConnectionBanner, EngineNotice, FileHeader, TopBar } from "./components/TopBar";
import { ExampleChips, PromptBar } from "./components/PromptBar";
import { StepPlayer } from "./components/LeftColumn";
import { BuildProgress, EditStatus, EventLog, FailureCard, LatencyHUD, Toast, WarningBanner } from "./components/Status";
import { PartsList, RightColumn } from "./components/RightColumn";
import { AddPartPicker, ConnectDialog, PartInspector, ResizePanel, SwapDrawer } from "./components/Overlays";
import { FocusCard, FocusExit } from "./components/FocusCard";
import { bindVoiceKeys } from "./voice/voice";
import { Library } from "./components/Library";
import { LandingHero } from "./components/Landing";
import { startAutosave } from "./library/autosave";
import { Viewport3D } from "./three/Viewport3D";
import { BotLab } from "./bot/BotLab";
import { CanvasTabs } from "./components/CanvasTabs";
import { startCanvasPersist } from "./state/canvases";
import { ProjectPanel } from "./project/ProjectPanel";
import { startLinkPruning } from "./project/project";
import { AgentStage } from "./bot/AgentStage";
import { ThoughtTrace } from "./bot/ThoughtTrace";
import { Explainer } from "./bot/Explainer";
import { CandidateFlyby } from "./bot/CandidateFlyby";
import { SimView } from "./sim/SimView";
import { useSimPanel } from "./sim/simPanelStore";

function useKeys() {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      const inField = !!t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable);
      // Esc from a field (the prompt, the explode slider) leaves the field and steps back as usual
      if (inField && e.key === "Escape") t.blur();
      else if (inField) return;
      const tab = e.altKey && !e.metaKey && !e.ctrlKey ? ({ Digit1: "design", Digit2: "build", Digit3: "code" } as const)[e.code as "Digit1"] : undefined;
      if (tab) {
        e.preventDefault();
        useApp.setState({ rightTab: tab });
        return;
      }
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "l" || e.key === "L") useApp.setState((s) => ({ logOpen: !s.logOpen }));
      // Esc steps back one level: out of a drawer opened from focus, then out of focus itself
      if (e.key === "Escape")
        useApp.setState((s) =>
          s.focusKey && s.overlay !== "focus"
            ? { overlay: "focus", moving: null, inspectPartId: null }
            : { overlay: null, moving: null, inspectPartId: null, focusKey: null, selection: s.focusKey ? null : s.selection },
        );
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}

function Home() {
  return (
    <main className="home landing">
      <LandingHero />
    </main>
  );
}

function Drafts() {
  return (
    <main className="home landing drafts">
      <Library />
    </main>
  );
}

function RightOverlay() {
  const overlay = useApp((s) => s.overlay);
  const selection = useApp((s) => s.selection);
  const inspectPartId = useApp((s) => s.inspectPartId);
  const focusKey = useApp((s) => s.focusKey);
  if (overlay === "focus" && focusKey) return <FocusCard />;
  if (overlay === "inspector" && (selection || inspectPartId)) return <PartInspector />;
  if (overlay === "swap" && selection) return <SwapDrawer />;
  if (overlay === "resize") return <ResizePanel />;
  return null;
}

/** A canvas with no build yet (or one still being fetched after a reload): just the prompt. */
function EmptyCanvas() {
  const restoring = useApp((s) => s.canvasRestoring.includes(s.activeCanvas));
  return (
    <main className="workspace">
      <aside className="leftcol" aria-label="Layers">
        <FileHeader />
      </aside>
      <section className="centre">
        <CanvasTabs />
        <div className="canvas-empty">
          {restoring ? (
            <p className="muted">Loading this canvas's build again…</p>
          ) : (
            <div className="canvas-empty-inner">
              <h2>Describe a device for this canvas.</h2>
              <PromptBar autoFocus />
              <ExampleChips />
            </div>
          )}
        </div>
      </section>
      <aside className="rightcol-wrap" aria-label="Details" />
    </main>
  );
}

function Workspace() {
  const overlay = useApp((s) => s.overlay);
  const empty = useApp((s) => s.build === null);
  if (empty) return <EmptyCanvas />;
  return (
    <main className="workspace">
      <aside className="leftcol" aria-label="Layers">
        <FileHeader />
        <StepPlayer />
        <PartsList />
      </aside>
      <section className="centre">
        <CanvasTabs />
        <Viewport3D />
        <ProjectPanel />
        <div className="centre-top">
          <BuildProgress />
          <WarningBanner />
        </div>
        <LatencyHUD />
        <div className="centre-mid">
          <FailureCard />
        </div>
        <div className="centre-bottom">
          <FocusExit />
          <EditStatus />
          <PromptBar docked />
        </div>
      </section>
      <aside className="rightcol-wrap" aria-label="Details">
        <RightColumn />
        <RightOverlay />
      </aside>
      {overlay === "connect" && <ConnectDialog />}
      {overlay === "addpart" && <AddPartPicker />}
      <AgentStage />
      <ThoughtTrace />
      <CandidateFlyby />
      <Explainer />
    </main>
  );
}

const BOTLAB = new URLSearchParams(window.location.search).get("botlab") === "1";

export function App() {
  if (BOTLAB) return <BotLab />;
  return <Main />;
}

function Main() {
  useKeys();
  useEffect(() => bindVoiceKeys(), []);
  useEffect(() => startAutosave(), []);
  useEffect(() => startCanvasPersist(), []);
  useEffect(() => startLinkPruning(), []);
  const screen = useApp((s) => s.screen);
  const simOpen = useSimPanel((s) => s.open) && screen === "workspace";
  if (simOpen) return <SimView />;
  return (
    <div className="app">
      {screen !== "workspace" && <TopBar />}
      <EngineNotice />
      <ConnectionBanner />
      {screen === "home" ? <Home /> : screen === "drafts" ? <Drafts /> : <Workspace />}
      <EventLog />
      <Toast />
    </div>
  );
}
