// Product-shot mode (?shot=<build_id>, used by scripts/render-shots.mjs): the finished device alone, for the
// library. No floor grid, no backdrop colour (the canvas stays transparent), no view cube, no post pass;
// only the soft contact shadow under the product stays, so it still sits on something.
export const SHOT_ID: string | null = typeof window === "undefined" ? null : new URLSearchParams(window.location.search).get("shot");
