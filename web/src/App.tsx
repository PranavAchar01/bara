import { useEffect } from "react";
import { useApp } from "./state/store";
import { ConnectionBanner, EngineNotice, FileHeader, TopBar } from "./components/TopBar";
import { ExampleChips, PromptBar } from "./components/PromptBar";
import { StepPlayer } from "./components/LeftColumn";
import { BuildProgress, EditStatus, EventLog, FailureCard, LatencyHUD, Toast, WarningBanner } from "./components/Status";
import { PartsList, RightColumn } from "./components/RightColumn";
import { AddPartPicker, ConnectDialog, PartInspector, ResizePanel, SwapDrawer } from "./components/Overlays";
import { FocusCard } from "./components/FocusCard";
import { SaysLine, SelectionBar } from "./components/SelectionBar";
import { Icon } from "./ui/common";
import { bindBuildVoice, bindVoiceKeys } from "./voice/voice";
import { Library } from "./components/Library";
import { AgentSteps, LandingHero } from "./components/Landing";
import { startAutosave } from "./library/autosave";
import { Viewport3D } from "./three/Viewport3D";
import { BotLab } from "./bot/BotLab";
import { CanvasTabs } from "./components/CanvasTabs";
import { startCanvasPersist } from "./state/canvases";
import { startAutoShots } from "./library/shots";
import { AgentStage } from "./bot/AgentStage";
import { ThoughtTrace } from "./bot/ThoughtTrace";
import { Explainer } from "./bot/Explainer";
import { CandidateFlyby } from "./bot/CandidateFlyby";
import { SimView } from "./sim/SimView";
import { useSimPanel } from "./sim/simPanelStore";
import { ShotPage } from "./components/ShotPage";
import { SHOT_ID } from "./three/shot";

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
      // Esc steps back one level: a drawer, then a part pulled out, then the selection, then the details panel
      if (e.key === "Escape")
        useApp.setState((s) =>
          s.focusKey && s.overlay !== "focus"
            ? { overlay: "focus", moving: null, inspectPartId: null }
            : s.focusKey || s.selection || s.overlay
              ? { overlay: null, moving: null, inspectPartId: null, focusKey: null, selection: s.focusKey ? null : s.selection && !s.overlay ? null : s.selection }
              : { panels: { ...s.panels, details: false } },
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
      <AgentSteps />
    </main>
  );
}

/** Every build made here, on a page of its own (the top bar's Library button). */
function LibraryPage() {
  return (
    <main className="home library-page">
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

/** The details panel opens when asked for, or when an action needs it (swap, details, resize). */
function useDetailsOpen(): boolean {
  return useApp((s) => s.panels.details || s.overlay === "swap" || s.overlay === "inspector" || s.overlay === "resize");
}

function closeDetails() {
  useApp.setState((s) => ({
    panels: { ...s.panels, details: false },
    overlay: s.overlay === "focus" ? "focus" : null,
  }));
}

/** A canvas with no build yet (or one still being fetched after a reload): Bara asks what it should be. */
function EmptyCanvas() {
  const restoring = useApp((s) => s.canvasRestoring.includes(s.activeCanvas));
  return (
    <div className="canvas-empty">
      {restoring ? (
        <span className="canvas-loading" aria-label="Loading this canvas's build again">
          <i />
          <i />
        </span>
      ) : (
        <div className="canvas-empty-inner">
          <span className="empty-eyes" aria-hidden>
            <i />
            <i />
          </span>
          <h2>What should this one be?</h2>
          <ExampleChips />
        </div>
      )}
    </div>
  );
}

/**
 * The workspace, canvas first: the device fills the window under a thin strip of tabs and tools; the
 * prompt waits at the bottom with the selection pill above it. The parts list and the details are side
 * panels over the canvas, closed until asked for (WorkTools) or until an action needs one.
 */
function Workspace() {
  const overlay = useApp((s) => s.overlay);
  const empty = useApp((s) => s.build === null);
  const layers = useApp((s) => s.panels.layers);
  const details = useDetailsOpen();
  return (
    <main className="workspace canvas-first">
      <section className="centre">
        <CanvasTabs />
        {empty ? (
          <EmptyCanvas />
        ) : (
          <>
            <Viewport3D />
            <div className="centre-top">
              <BuildProgress />
              <WarningBanner />
            </div>
            <LatencyHUD />
            <div className="centre-mid">
              <FailureCard />
            </div>
          </>
        )}
        <div className="centre-bottom">
          <SaysLine />
          <SelectionBar />
          <EditStatus />
          <PromptBar docked autoFocus={empty} />
        </div>
      </section>
      {layers && !empty && (
        <aside className="float-panel float-left leftcol" aria-label="Parts">
          <FileHeader />
          <StepPlayer />
          <PartsList />
        </aside>
      )}
      {details && !empty && (
        <aside className="float-panel float-right rightcol-wrap" aria-label="Details">
          <button type="button" className="float-close" onClick={closeDetails} aria-label="Close details" title="Close (Esc)">
            <Icon name="x" />
          </button>
          <RightColumn />
          <RightOverlay />
        </aside>
      )}
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
  if (SHOT_ID) return <ShotPage buildId={SHOT_ID} />;
  return <Main />;
}

function Main() {
  useKeys();
  useEffect(() => bindVoiceKeys(), []);
  useEffect(() => bindBuildVoice(), []);
  useEffect(() => startAutosave(), []);
  useEffect(() => startCanvasPersist(), []);
  useEffect(() => startAutoShots(), []);
  const screen = useApp((s) => s.screen);
  const simOpen = useSimPanel((s) => s.open) && screen === "workspace";
  if (simOpen) return <SimView />;
  return (
    <div className="app">
      {screen !== "workspace" && <TopBar />}
      <EngineNotice />
      <ConnectionBanner />
      {screen === "home" ? <Home /> : screen === "library" ? <LibraryPage /> : <Workspace />}
      <EventLog />
      <Toast />
    </div>
  );
}
