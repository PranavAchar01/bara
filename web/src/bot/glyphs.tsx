// Tiny things the bot thinks about: one-colour line drawings on a 16 px grid,
// drawn in the current text colour so they follow the theme.
import type { ThoughtIcon } from "./mood";

const PATHS: Record<ThoughtIcon, string[]> = {
  lines: ["M3 4h10", "M3 8h8", "M3 12h6"],
  lens: ["M7 7m-4 0a4 4 0 1 0 8 0a4 4 0 1 0 -8 0", "M10 10l3.5 3.5"],
  switch: ["M3.5 3.5h9v9h-9z", "M6 6h4v4h-4z", "M8 6v-2.5"],
  chip: ["M4.5 4.5h7v7h-7z", "M6 2.5v2M8 2.5v2M10 2.5v2M6 11.5v2M8 11.5v2M10 11.5v2M2.5 6h2M2.5 10h2M11.5 6h2M11.5 10h2"],
  grid: ["M3 3h4v4h-4zM9 3h4v4h-4zM3 9h4v4h-4zM9 9h4v4h-4z"],
  box: ["M8 2.5l5 2.5v6l-5 2.5l-5-2.5v-6z", "M3 5l5 2.5l5-2.5", "M8 7.5v6"],
  trace: ["M2.5 12h3l2-4h3l2-4h1", "M2.5 12m-1 0a1 1 0 1 0 2 0a1 1 0 1 0 -2 0", "M13.5 4m-1 0a1 1 0 1 0 2 0a1 1 0 1 0 -2 0"],
  code: ["M6 4l-3.5 4l3.5 4", "M10 4l3.5 4l-3.5 4"],
  spark: ["M8 2l1.3 4.7l4.7 1.3l-4.7 1.3l-1.3 4.7l-1.3-4.7l-4.7-1.3l4.7-1.3z"],
  question: ["M5.5 5.5a2.5 2.5 0 1 1 3.5 2.3c-.7.3-1 .9-1 1.6v.6", "M8 12.5v.2"],
  heart: ["M8 13s-5-3-5-6.5a2.6 2.6 0 0 1 5-1a2.6 2.6 0 0 1 5 1c0 3.5-5 6.5-5 6.5z"],
  zzz: ["M3 4h4l-4 4h4", "M9 8h4l-4 4h4"],
};

export function ThoughtGlyph(props: { icon: ThoughtIcon }) {
  return (
    <svg viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {PATHS[props.icon].map((d, i) => (
        <path key={i} d={d} />
      ))}
    </svg>
  );
}
