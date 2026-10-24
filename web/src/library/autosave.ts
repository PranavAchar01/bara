// Keeps the library current: whenever the open build changes (status, revision, parts), it is
// saved a moment later with a fresh snapshot of the canvas. Builds on background canvas tabs
// are saved too, keeping the thumbnail they had.
import type { Build } from "../spec/types";
import type { ViewState } from "../state/view";
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
  await keep(b, s.view, b.parts.length ? snapshotCanvas(canvas) : null);
}

async function keep(b: Build, view: ViewState, thumb: string | null): Promise<void> {
  const s = useApp.getState();
  const now = Date.now();
  try {
    await saveEntry({
      card: {
        build_id: b.build_id,
        prompt: b.prompt,
        summary: summarize(b, view),
        status: String(b.status),
        parts: b.parts.reduce((n, p) => n + (p.quantity || 1), 0),
        createdAt: now,
        updatedAt: now,
        thumb,
        mock: s.mode.mock,
      },
      build: b,
      view,
    });
  } catch {
    // storage full or blocked: the build is still on screen, just not kept
  }
}

/** Background builds by key, saved without a new thumbnail when they finish (null thumb keeps the last one). */
function watchBackground(): () => void {
  const seen = new Map<string, string>();
  return useApp.subscribe((s) => {
    for (const c of Object.values(s.canvasStash)) {
      const b = c.build;
      if (!b || !b.prompt) continue;
      const k = `${b.status}:${b.revision}:${c.view.done ? 1 : 0}`;
      if (seen.get(b.build_id) === k) continue;
      seen.set(b.build_id, k);
      if (b.status !== "running") void keep(b, c.view, null);
    }
  });
}

/** Starts saving; returns a stop function. */
export function startAutosave(): () => void {
  void refreshLibrary();
  const stopBackground = watchBackground();
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
    stopBackground();
    if (timer) window.clearTimeout(timer);
    if (late) window.clearTimeout(late);
  };
}
