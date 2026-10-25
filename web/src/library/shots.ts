// Product shots: the finished device alone, for the library. ShotPage draws one build (?shot=<id>) with no
// floor, grid or backdrop and crops it here; a browser that finishes a build shoots it in a hidden frame and
// sends it to the engine (startAutoShots), and scripts/render-shots.mjs does the same for older builds.
import { authHeaders, serverUrl } from "../net/mode";
import { paths } from "../net/rest";
import { useApp } from "../state/store";
import { refreshLibrary } from "./library";

/** The shot's frame; the device is centred in it with a margin. */
export const SHOT_W = 1200;
export const SHOT_H = 900;
const PAD = 0.08;

/** Crop a transparent render to the drawn pixels, centre them in the shot frame and encode WebP; null if empty. */
export function cropShot(src: HTMLCanvasElement): string | null {
  const probe = document.createElement("canvas");
  probe.width = src.width;
  probe.height = src.height;
  const p = probe.getContext("2d", { willReadFrequently: true });
  if (!p || !probe.width || !probe.height) return null;
  p.drawImage(src, 0, 0);
  const px = p.getImageData(0, 0, probe.width, probe.height).data;
  let x0 = probe.width;
  let y0 = probe.height;
  let x1 = -1;
  let y1 = -1;
  for (let y = 0; y < probe.height; y++)
    for (let x = 0; x < probe.width; x++)
      if (px[(y * probe.width + x) * 4 + 3] > 8) {
        if (x < x0) x0 = x;
        if (x > x1) x1 = x;
        if (y < y0) y0 = y;
        if (y > y1) y1 = y;
      }
  if (x1 < 0) return null;
  const w = x1 - x0 + 1;
  const h = y1 - y0 + 1;
  const k = Math.min((SHOT_W * (1 - 2 * PAD)) / w, (SHOT_H * (1 - 2 * PAD)) / h);
  const out = document.createElement("canvas");
  out.width = SHOT_W;
  out.height = SHOT_H;
  const o = out.getContext("2d");
  if (!o) return null;
  o.imageSmoothingQuality = "high";
  o.drawImage(probe, x0, y0, w, h, (SHOT_W - w * k) / 2, (SHOT_H - h * k) / 2, w * k, h * k);
  return out.toDataURL("image/webp", 0.9);
}

/** How long a shot may take before it is given up (models can be slow to arrive). */
const SHOT_TIMEOUT_MS = 90_000;

/** Draw one stored build in a hidden frame of this same app and send the shot to the engine. */
export async function takeShot(buildId: string): Promise<boolean> {
  const frame = document.createElement("iframe");
  frame.src = `${window.location.pathname}?shot=${encodeURIComponent(buildId)}`;
  frame.setAttribute("aria-hidden", "true");
  frame.tabIndex = -1;
  // kept on screen (an off-screen frame may stop drawing) but invisible and out of the way
  frame.style.cssText = "position:fixed;left:0;top:0;width:1400px;height:1000px;border:0;opacity:0.001;pointer-events:none;z-index:-1";
  document.body.appendChild(frame);
  try {
    const data = await new Promise<string | null>((resolve) => {
      const started = Date.now();
      const poll = window.setInterval(() => {
        const w = frame.contentWindow as (Window & { __shot?: string; __shotData?: string | null }) | null;
        const state = w?.__shot;
        if (state === "shot" || state === "failed" || Date.now() - started > SHOT_TIMEOUT_MS) {
          window.clearInterval(poll);
          resolve(state === "shot" ? (w?.__shotData ?? null) : null);
        }
      }, 400);
    });
    if (!data) return false;
    const bytes = await (await fetch(data)).blob();
    const res = await fetch(serverUrl(paths.libraryShot(buildId)), { method: "PUT", headers: { ...authHeaders(), "content-type": "image/webp" }, body: bytes });
    if (!res.ok) return false;
    void refreshLibrary();
    return true;
  } finally {
    frame.remove();
  }
}

/**
 * Shoots each build as it finishes here, and again when a finished build is edited: the engine has just
 * stored it, so the shot can join it. Opening a stored build does not count; it has its shot already.
 */
export function startAutoShots(): () => void {
  const seen = new Map<string, string>();
  const queue: string[] = [];
  let busy = false;
  let timer = 0;
  const pump = async () => {
    if (busy) return;
    const id = queue.shift();
    if (!id) return;
    busy = true;
    await takeShot(id).catch(() => false);
    busy = false;
    void pump();
  };
  const unsub = useApp.subscribe((s, prev) => {
    const b = s.build;
    if (!b || s.mode.mock || s.replaying) return;
    const key = `${b.status}:${b.revision}`;
    const was = prev.build?.build_id === b.build_id ? `${prev.build.status}:${prev.build.revision}` : seen.get(b.build_id);
    seen.set(b.build_id, key);
    // only a change seen here: a build finishing, or a finished build changing revision
    if (b.status !== "done" || was === undefined || was === key || s.openedFromLibrary === b.build_id) return;
    if (!queue.includes(b.build_id)) queue.push(b.build_id);
    // after the bot's walk through the result, so the shot does not compete with it
    window.clearTimeout(timer);
    timer = window.setTimeout(() => void pump(), 6000);
  });
  return () => {
    unsub();
    window.clearTimeout(timer);
  };
}
