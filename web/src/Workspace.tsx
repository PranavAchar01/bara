// The workspace, loaded on its own so the landing does not carry the 3D canvas and everything around it.
import { useApp } from "./state/store";
import { FileHeader } from "./components/TopBar";
import { ExampleChips, PromptBar } from "./components/PromptBar";
import { BaraBot } from "./bot/BaraBot";
import { StepPlayer } from "./components/LeftColumn";
import { BuildProgress, EditStatus, FailureCard, LatencyHUD, WarningBanner } from "./components/Status";
import { PartsList, RightColumn } from "./components/RightColumn";
import { AddPartPicker, ConnectDialog, PartInspector, ResizePanel, SwapDrawer } from "./components/Overlays";
import { FocusCard } from "./components/FocusCard";
import { FitCheck } from "./components/FitCheck";
import { SaysLine, SelectionBar } from "./components/SelectionBar";
import { Icon } from "./ui/common";
import { Viewport3D } from "./three/Viewport3D";
import { CanvasTabs } from "./components/CanvasTabs";
import { ProjectPanel } from "./project/ProjectPanel";
import { AgentStage } from "./bot/AgentStage";
import { ThoughtTrace } from "./bot/ThoughtTrace";
import { Explainer } from "./bot/Explainer";
import { CandidateFlyby } from "./bot/CandidateFlyby";

function RightOverlay() {
  const overlay = useApp((s) => s.overlay);
  const selection = useApp((s) => s.selection);
  const inspectPartId = useApp((s) => s.inspectPartId);
  const focusKey = useApp((s) => s.focusKey);
  if (overlay === "focus" && focusKey) return <FocusCard />;
  if (overlay === "inspector" && (selection || inspectPartId)) return <PartInspector />;
  if (overlay === "swap" && selection) return <SwapDrawer />;
  if (overlay === "resize") return <ResizePanel />;
  if (overlay === "fit") return <FitCheck />;
  return null;
}

/** The details panel opens when asked for, or when an action needs it (swap, details, resize). */
function useDetailsOpen(): boolean {
  return useApp((s) => s.panels.details || s.overlay === "swap" || s.overlay === "inspector" || s.overlay === "resize" || s.overlay === "fit");
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
  const starting = useApp((s) => s.pendingStart?.prompt ?? null);
  return (
    <div className="canvas-empty">
      {restoring ? (
        <span className="canvas-loading" aria-label="Loading this canvas's build again">
          <i />
          <i />
        </span>
      ) : starting ? (
        <div className="canvas-empty-inner canvas-starting" role="status">
          <BaraBot size={72} mood="thinking" />
          <h2>{starting}</h2>
          <p className="muted">Starting the build…</p>
        </div>
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
export default function Workspace() {
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
            <ProjectPanel />
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
