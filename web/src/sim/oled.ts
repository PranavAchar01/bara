// Draws a monochrome OLED frame: the lines the firmware shows, in a small bitmap font look.
export function drawOled(ctx: CanvasRenderingContext2D, lines: string[], w: number, h: number): void {
  ctx.fillStyle = "#05070a";
  ctx.fillRect(0, 0, w, h);
  if (!lines.length) return;
  // about 11 px rows on the panel itself: three on a 128x32, six on a 128x64
  const rows = Math.max(lines.length, Math.round((h / w) * 12));
  const lh = Math.floor(h / rows);
  ctx.fillStyle = "#cfe9ff";
  ctx.font = `bold ${Math.max(7, lh - 2)}px "Atkinson Hyperlegible Mono", ui-monospace, Menlo, monospace`;
  ctx.textBaseline = "top";
  lines.forEach((line, i) => ctx.fillText(line, 2, i * lh + 1, w - 4));
}
