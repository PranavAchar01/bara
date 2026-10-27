// Line icons for the workspace's few controls (top strip, selection pill, view button): 16 px, one
// stroke weight, currentColor, so they sit with the mono labels and the ink of the rest of the UI.
export type GlyphName =
  | "undo"
  | "redo"
  | "versions"
  | "layers"
  | "details"
  | "swap"
  | "colour"
  | "move"
  | "remove"
  | "ask"
  | "more"
  | "around"
  | "pull"
  | "view"
  | "fit";

const PATHS: Record<GlyphName, string> = {
  undo: "M6 4.5 3 7.5l3 3M3.5 7.5H10a3 3 0 0 1 0 6H8",
  redo: "M10 4.5l3 3-3 3M12.5 7.5H6a3 3 0 0 0 0 6h2",
  versions: "M8 4.5V8l2.2 1.4M2.8 8a5.2 5.2 0 1 0 1.5-3.7M2.5 2.8v2.6h2.6",
  layers: "M8 2.5 2.5 5.5 8 8.5l5.5-3zM2.5 8.2 8 11.2l5.5-3M2.5 10.9 8 13.9l5.5-3",
  details: "M2.5 3.5h11v9h-11zM10 3.5v9",
  swap: "M3 5.5h9.5M10 3l2.5 2.5L10 8M13 10.5H3.5M6 8l-2.5 2.5L6 13",
  colour: "M8 2.5c2.5 3 4 5 4 7a4 4 0 0 1-8 0c0-2 1.5-4 4-7z",
  move: "M8 2v12M2 8h12M8 2 6.3 3.7M8 2l1.7 1.7M8 14l-1.7-1.7M8 14l1.7-1.7M2 8l1.7-1.7M2 8l1.7 1.7M14 8l-1.7-1.7M14 8l-1.7 1.7",
  remove: "M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.6 8.5h5.8l.6-8.5",
  ask: "M3 3.5h10v7H7l-3 2.5v-2.5H3z",
  more: "M3.5 8h.01M8 8h.01M12.5 8h.01",
  around: "M5.5 5.5h5v5h-5zM2.5 2.5h2.2M2.5 2.5v2.2M13.5 2.5h-2.2M13.5 2.5v2.2M2.5 13.5h2.2M2.5 13.5v-2.2M13.5 13.5h-2.2M13.5 13.5v-2.2",
  pull: "M8 13V4M4.5 7.5 8 4l3.5 3.5M3 13.5h10",
  fit: "M2.5 5V2.5H5M11 2.5h2.5V5M13.5 11v2.5H11M5 13.5H2.5V11M5.5 6.5h5v3h-5z",
  view: "M1.8 8s2.3-4.3 6.2-4.3 6.2 4.3 6.2 4.3-2.3 4.3-6.2 4.3S1.8 8 1.8 8zM8 6.2a1.8 1.8 0 1 0 0 3.6 1.8 1.8 0 0 0 0-3.6z",
};

export function Glyph(props: { name: GlyphName; size?: number }) {
  const s = props.size ?? 16;
  const dots = props.name === "more";
  return (
    <svg width={s} height={s} viewBox="0 0 16 16" aria-hidden fill="none" stroke="currentColor" strokeWidth={dots ? 2.6 : 1.5} strokeLinecap="round" strokeLinejoin="round">
      <path d={PATHS[props.name]} />
    </svg>
  );
}
