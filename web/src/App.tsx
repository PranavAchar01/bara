import { useEffect } from "react";
import { useApp } from "./state/store";
import { ConnectionBanner, EngineNotice, FileHeader, TopBar } from "./components/TopBar";
import { ExampleChips, PromptBar } from "./components/PromptBar";
import { StepPlayer } from "./components/LeftColumn";
import { BuildProgress, EditStatus, EventLog, FailureCard, LatencyHUD, Toast, WarningBanner } from "./components/Status";
import { PartsList, RightColumn } from "./components/RightColumn";
import { AddPartPicker, ConnectDialog, PartInspector, ResizePanel, SwapDrawer } from "./components/Overlays";
import { Viewport3D } from "./three/Viewport3D";
import { BotLab } from "./bot/BotLab";

function useKeys() {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable)) return;
      const tab = e.altKey && !e.metaKey && !e.ctrlKey ? ({ Digit1: "design", Digit2: "build", Digit3: "code" } as const)[e.code as "Digit1"] : undefined;
      if (tab) {
        e.preventDefault();
        useApp.setState({ rightTab: tab });
        return;
      }
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "l" || e.key === "L") useApp.setState((s) => ({ logOpen: !s.logOpen }));
      if (e.key === "Escape") useApp.setState({ overlay: null, moving: null, inspectPartId: null });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}

function Home() {
  const health = useApp((s) => s.health);
  return (
    <main className="home">
      <div className="home-inner">
        <h1>Describe a device. It gets built from open hardware.</h1>
        <p className="muted">
          It reuses an open design when one fits, otherwise composes one from open source parts, and shows every decision, part, case, board and firmware
          as it goes.
        </p>
        <PromptBar autoFocus />
        <ExampleChips />
        {health && (
          <p className="muted small home-meta">
            {health.part_count ?? 0} parts and {health.design_count ?? 0} designs in the catalog
          </p>
        )}
      </div>
    </main>
  );
}

function RightOverlay() {
  const overlay = useApp((s) => s.overlay);
  const selection = useApp((s) => s.selection);
  const inspectPartId = useApp((s) => s.inspectPartId);
  if (overlay === "inspector" && (selection || inspectPartId)) return <PartInspector />;
  if (overlay === "swap" && selection) return <SwapDrawer />;
  if (overlay === "resize") return <ResizePanel />;
  return null;
}

function Workspace() {
  const overlay = useApp((s) => s.overlay);
  return (
    <main className="workspace">
      <aside className="leftcol" aria-label="Layers">
        <FileHeader />
        <StepPlayer />
        <PartsList />
      </aside>
      <section className="centre">
        <Viewport3D />
        <div className="centre-top">
          <BuildProgress />
          <WarningBanner />
        </div>
        <LatencyHUD />
        <div className="centre-mid">
          <FailureCard />
        </div>
        <div className="centre-bottom">
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
  const screen = useApp((s) => s.screen);
  return (
    <div className="app">
      {screen === "home" && <TopBar />}
      <EngineNotice />
      <ConnectionBanner />
      {screen === "home" ? <Home /> : <Workspace />}
      <EventLog />
      <Toast />
    </div>
  );
}
