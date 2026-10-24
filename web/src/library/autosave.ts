// Keeps the library current: whenever the open build changes (status, revision, parts), it is
// saved a moment later with a fresh snapshot of the canvas.
import { useApp } from "../state/store";
import { refreshLibrary, saveEntry, snapshotCanvas, summarize } from "./library";

function keyOf(): string | null {
  const s = useApp.getState();
  const b = s.build;
  if (!b) return null;
  return `${b.build_id}:${b.status}:${b.revision}:${b.parts.length}:${b.enclosures?.length ?? 0}:${s.view.done ? 1 : 0}`;
}

async function save(): Promise<void> {
  const s = useApp.getState();
  const b = s.build;
  if (!b || !b.prompt) return;
  // only snapshot what is on screen: the workspace canvas showing this build
  const canvas = s.screen === "workspace" && s.focusKey === null ? document.querySelector<HTMLCanvasElement>(".viewport canvas") : null;
  const now = Date.now();
  try {
    await saveEntry({
      card: {
        build_id: b.build_id,
        prompt: b.prompt,
        summary: summarize(b, s.view),
        status: String(b.status),
        parts: b.parts.reduce((n, p) => n + (p.quantity || 1), 0),
        createdAt: now,
        updatedAt: now,
        thumb: b.parts.length ? snapshotCanvas(canvas) : null,
        mock: s.mode.mock,
      },
      build: b,
      view: s.view,
    });
  } catch {
    // storage full or blocked: the build is still on screen, just not kept
  }
}

/** Starts saving; returns a stop function. */
export function startAutosave(): () => void {
  void refreshLibrary();
  let last = keyOf();
  let timer: number | null = null;
  let late: number | null = null;
  const unsub = useApp.subscribe(() => {
    const k = keyOf();
    if (k === null || k === last) return;
    last = k;
    const running = useApp.getState().build?.status === "running";
    if (timer) window.clearTimeout(timer);
    if (late) window.clearTimeout(late);
    timer = window.setTimeout(() => void save(), running ? 4000 : 1200);
    // models keep landing after done: take the thumbnail again once they have drawn
    if (!running) late = window.setTimeout(() => void save(), 5000);
  });
  return () => {
    unsub();
    if (timer) window.clearTimeout(timer);
    if (late) window.clearTimeout(late);
  };
}
