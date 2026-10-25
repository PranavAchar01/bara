import { lazy, Suspense, useEffect } from "react";
import { useApp } from "./state/store";
import { ConnectionBanner, EngineNotice, TopBar } from "./components/TopBar";
import { useBuildDialog } from "./components/buildDialogStore";
import { useRouteSync } from "./pages/routes";
import { EventLog, Toast } from "./components/Status";
import { bindBuildVoice, bindVoiceKeys } from "./voice/voice";
import { Landing } from "./components/Landing";
import { Handoff, useHandoffRunning } from "./components/Handoff";
import { startAutosave } from "./library/autosave";
import { startCanvasPersist } from "./state/canvases";
import { startLinkPruning } from "./project/project";
import { startAutoShots } from "./library/shots";
import { useSimPanel } from "./sim/simPanelStore";
import { SHOT_ID } from "./three/shot";

// The landing paints with only what it shows. The workspace (the 3D canvas and its panels), the Build
// pop-up, the Library page, the simulator and the dev pages load on their own; the landing fetches the
// workspace once it has gone idle, so pressing Build never waits on it.
const loadWorkspace = () => import("./Workspace");
const Workspace = lazy(loadWorkspace);
const BuildDialog = lazy(() => import("./components/BuildDialog"));
const LibraryPage = lazy(() => import("./components/Library").then((m) => ({ default: m.LibraryPage })));
const SimView = lazy(() => import("./sim/SimView").then((m) => ({ default: m.SimView })));
const BotLab = lazy(() => import("./bot/BotLab").then((m) => ({ default: m.BotLab })));
const ShotPage = lazy(() => import("./components/ShotPage").then((m) => ({ default: m.ShotPage })));

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
      // while simulating, letters belong to the device: L types an l instead of opening the log
      if ((e.key === "l" || e.key === "L") && !useSimPanel.getState().open) useApp.setState((s) => ({ logOpen: !s.logOpen }));
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
  useEffect(() => {
    const idle = window.requestIdleCallback ?? ((f: () => void) => window.setTimeout(f, 1500));
    const h = idle(() => void loadWorkspace().then(() => import("./components/BuildDialog")), { timeout: 4000 });
    return () => (window.cancelIdleCallback ?? window.clearTimeout)(h);
  }, []);
  return <Landing />;
}

function Drafts() {
  return (
    <main className="home libmain">
      <LibraryPage />
    </main>
  );
}

const BOTLAB = new URLSearchParams(window.location.search).get("botlab") === "1";

export function App() {
  if (BOTLAB || SHOT_ID)
    return <Suspense fallback={null}>{BOTLAB ? <BotLab /> : <ShotPage buildId={SHOT_ID ?? ""} />}</Suspense>;
  return <Main />;
}

function Main() {
  useKeys();
  useRouteSync();
  useEffect(() => bindVoiceKeys(), []);
  useEffect(() => bindBuildVoice(), []);
  useEffect(() => startAutosave(), []);
  useEffect(() => startCanvasPersist(), []);
  useEffect(() => startLinkPruning(), []);
  useEffect(() => startAutoShots(), []);
  const screen = useApp((s) => s.screen);
  const simOpen = useSimPanel((s) => s.open) && screen === "workspace";
  const handing = useHandoffRunning();
  const dialog = useBuildDialog((s) => s.open);
  return (
    <div className={`app ${handing ? "ho-run" : ""} ${simOpen ? "sim-on" : ""}`}>
      {screen !== "workspace" && <TopBar />}
      <EngineNotice />
      <ConnectionBanner />
      <Suspense fallback={<main className="home" aria-busy="true" />}>{screen === "home" ? <Home /> : screen === "drafts" ? <Drafts /> : <Workspace />}</Suspense>
      <EventLog />
      <Toast />
      <Suspense fallback={null}>{dialog && <BuildDialog />}</Suspense>
      <Handoff screen={screen} />
      <Suspense fallback={null}>{simOpen && <SimView />}</Suspense>
    </div>
  );
}
