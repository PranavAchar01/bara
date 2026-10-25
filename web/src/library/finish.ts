// "Finish build": a build that did not reach done (failed, stopped, interrupted) is carried on by running
// its request again as a normal build. The engine has no resume for a stopped run, so this starts a new one
// from the same prompt; it opens in place (the canvas that shows the old build, or a fresh one from the
// library) and, once the engine has accepted it, the unfinished card is put away so the new build replaces it.
import { startBuild } from "../net/client";
import { useApp } from "../state/store";
import { addCanvas, canvasOfBuild, switchCanvas } from "../state/canvases";
import { deleteEntry } from "./library";

/** What a build is, in a word, for its card. Done is "Ready"; anything that stopped short needs finishing. */
export function stateLabel(status: string): string | null {
  switch (status) {
    case "done":
      return "Ready";
    case "failed":
    case "cancelled":
      return "Needs finishing";
    case "running":
      return "In progress";
    case "awaiting_input":
      return "Needs an answer";
    default:
      return null;
  }
}

/** Only a build that ended short of done can be finished. */
export function canFinish(status: string | null | undefined): boolean {
  return status === "failed" || status === "cancelled";
}

/** The card's sub-line: how many checks passed, only when every one did; otherwise the build's state. */
export function cardSubline(checks: number, allPassed: boolean): string {
  return allPassed && checks > 0 ? `${checks} checks passed` : "Ready";
}

/** Runs the unfinished build's request again, in place, and replaces its card once the new run is accepted. */
export function finishBuild(buildId: string, prompt: string): void {
  const s = useApp.getState();
  const showing = canvasOfBuild(s, buildId);
  if (showing) switchCanvas(showing);
  else if (s.build || s.pendingStart) addCanvas();
  useApp.setState({ screen: "workspace" });
  startBuild(prompt);
  const stop = useApp.subscribe((st) => {
    const id = st.build?.build_id;
    if (st.pendingStart || !id || id === buildId) return;
    stop();
    void deleteEntry(buildId).catch(() => {});
  });
  setTimeout(stop, 60_000);
}
