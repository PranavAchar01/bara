// What the device's display shows: the snake board in game mode, the typed text in typing mode.
// Drawn into a 2D canvas that the viewport uses as the display face's texture.
import type { RemoteScreen, Runtime } from "./runtime";
import type { DisplaySpec } from "./view";

interface Palette {
  bg: string;
  grid: string;
  snake: string;
  head: string;
  food: string;
  text: string;
  dim: string;
}

const COLOR: Palette = { bg: "#0c1624", grid: "#12233a", snake: "#4fcf86", head: "#b6ffd2", food: "#ff6b6b", text: "#e8f1ff", dim: "#7f93ad" };
const MONO: Palette = { bg: "#000000", grid: "#000000", snake: "#ffffff", head: "#ffffff", food: "#ffffff", text: "#ffffff", dim: "#8a8a8a" };

function wrap(text: string, cols: number): string[] {
  const lines: string[] = [];
  for (const raw of text.split("\n")) {
    if (raw.length === 0) lines.push("");
    for (let i = 0; i < raw.length; i += cols) lines.push(raw.slice(i, i + cols));
  }
  return lines;
}

function drawGame(ctx: CanvasRenderingContext2D, rt: Runtime, spec: DisplaySpec, p: Palette): void {
  const { w, h } = spec;
  const g = rt.game;
  const cell = Math.max(1, Math.floor(Math.min(w / g.cols, h / g.rows)));
  const ox = Math.floor((w - cell * g.cols) / 2);
  const oy = Math.floor((h - cell * g.rows) / 2);
  ctx.fillStyle = p.grid;
  if (!spec.mono) ctx.fillRect(ox, oy, cell * g.cols, cell * g.rows);
  else {
    ctx.strokeStyle = "#ffffff";
    ctx.lineWidth = 1;
    ctx.strokeRect(ox + 0.5, oy + 0.5, cell * g.cols - 1, cell * g.rows - 1);
  }
  const inset = cell > 3 ? 1 : 0;
  ctx.fillStyle = p.food;
  ctx.fillRect(ox + g.food[0] * cell + inset, oy + g.food[1] * cell + inset, cell - inset * 2, cell - inset * 2);
  g.body.forEach((b, i) => {
    ctx.fillStyle = i === 0 ? p.head : p.snake;
    ctx.fillRect(ox + b[0] * cell + inset, oy + b[1] * cell + inset, cell - inset * 2, cell - inset * 2);
  });
  const font = Math.max(6, Math.round(h / 9));
  ctx.font = `bold ${font}px ui-monospace, Menlo, monospace`;
  ctx.textBaseline = "top";
  ctx.fillStyle = p.text;
  ctx.fillText(`SCORE ${g.score}`, ox + 3, oy + 2);
  ctx.textAlign = "right";
  ctx.fillStyle = p.dim;
  ctx.fillText(`BEST ${g.best}`, ox + cell * g.cols - 3, oy + 2);
  ctx.textAlign = "center";
  const banner = g.status === "ready" ? "PRESS A TO START" : g.status === "paused" ? "PAUSED" : g.status === "over" ? "GAME OVER" : "";
  if (banner) {
    const bh = font * 1.9;
    ctx.fillStyle = spec.mono ? "#000000" : "rgba(8,14,24,0.82)";
    ctx.fillRect(ox, oy + (cell * g.rows - bh) / 2, cell * g.cols, bh);
    ctx.fillStyle = p.text;
    ctx.textBaseline = "middle";
    ctx.fillText(banner, ox + (cell * g.cols) / 2, oy + cell * g.rows / 2 + 1);
  }
  ctx.textAlign = "left";
}

function drawText(ctx: CanvasRenderingContext2D, rt: Runtime, spec: DisplaySpec, p: Palette, now: number): void {
  const { w, h } = spec;
  const lines = Math.max(2, Math.round(h / 9));
  const font = Math.floor(h / lines) - 1;
  ctx.font = `${font}px ui-monospace, Menlo, monospace`;
  ctx.textBaseline = "top";
  const cols = Math.max(4, Math.floor((w - 6) / (font * 0.6)));
  const shown = wrap(rt.terminal.text, cols);
  if (!shown.length) shown.push("");
  const tail = shown.slice(-lines);
  const caret = Math.floor(now / 500) % 2 === 0;
  tail.forEach((line, i) => {
    ctx.fillStyle = p.text;
    ctx.fillText(line, 3, 2 + i * (font + 1));
    if (i === tail.length - 1 && caret) {
      const cx = 3 + line.length * font * 0.6;
      ctx.fillRect(cx, 2 + i * (font + 1), Math.max(2, font * 0.5), font);
    }
  });
}

/** Pixel values 0..3 from the engine's packed framebuffer (four pixels a byte, low bits first). */
export function unpackFb(b64: string, w: number, h: number): Uint8Array {
  const bin = typeof atob === "function" ? atob(b64) : Buffer.from(b64, "base64").toString("binary");
  const out = new Uint8Array(w * h);
  for (let i = 0; i < out.length; i++) out[i] = (bin.charCodeAt(i >> 2) >> ((i & 3) * 2)) & 3;
  return out;
}

const SHADES_COLOR = ["#0c1624", "#4fcf86", "#ffd166", "#e8f1ff"];
const SHADES_MONO = ["#000000", "#ffffff", "#ffffff", "#ffffff"];
let stash: { key: string; px: Uint8Array } | null = null;
let paint: HTMLCanvasElement | null = null;

function drawRemote(ctx: CanvasRenderingContext2D, canvas: HTMLCanvasElement, r: RemoteScreen, spec: DisplaySpec, p: Palette): void {
  const { width: W, height: H } = canvas;
  ctx.textBaseline = "top";
  const say = (lines: string[]) => {
    const font = Math.max(8, Math.floor(H / Math.max(4, lines.length + 1)));
    ctx.font = `${font}px ui-monospace, Menlo, monospace`;
    ctx.fillStyle = p.text;
    lines.forEach((l, i) => ctx.fillText(l, 4, 3 + i * (font + 2)));
  };
  if (!r.powered) {
    ctx.fillStyle = "#000000";
    ctx.fillRect(0, 0, W, H);
    return;
  }
  if (r.bootloader) return say(["BOOTLOADER", "USB drive mode", "drop a .uf2 here", "reset to run the firmware"]);
  if (!r.fb) return say(r.rows.length ? r.rows : [""]);
  const { w, h, b64 } = r.fb;
  const key = `${w}x${h}:${b64}`;
  if (!stash || stash.key !== key) stash = { key, px: unpackFb(b64, w, h) };
  paint ??= document.createElement("canvas");
  paint.width = w;
  paint.height = h;
  const pctx = paint.getContext("2d");
  if (!pctx) return;
  const shades = spec.mono ? SHADES_MONO : SHADES_COLOR;
  const img = pctx.createImageData(w, h);
  const rgb = shades.map((c) => [parseInt(c.slice(1, 3), 16), parseInt(c.slice(3, 5), 16), parseInt(c.slice(5, 7), 16)]);
  for (let i = 0; i < w * h; i++) {
    const c = rgb[stash.px[i]];
    img.data.set([c[0], c[1], c[2], 255], i * 4);
  }
  pctx.putImageData(img, 0, 0);
  // the panel's off pixels fill the whole face, so the picture reads as the screen itself, not a box on it
  ctx.fillStyle = shades[0];
  ctx.fillRect(0, 0, W, H);
  const k = Math.min(W / w, H / h);
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(paint, (W - w * k) / 2, (H - h * k) / 2, w * k, h * k);
}

/** Paint the display for the runtime's mode. `now` is a millisecond clock, for the blinking caret. */
export function drawScreen(canvas: HTMLCanvasElement, rt: Runtime, spec: DisplaySpec, now: number): void {
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const p = spec.mono ? MONO : COLOR;
  ctx.fillStyle = p.bg;
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  if (rt.remote) drawRemote(ctx, canvas, rt.remote, spec, p);
  else if (rt.mode === "game") drawGame(ctx, rt, spec, p);
  else drawText(ctx, rt, spec, p, now);
}
