// The agent on stage: while a build runs, the bot leaves the prompt bar and
// works the canvas. It flies to what the build is touching, frames it with a
// selection box, and acts the step out (scan, drop, trace, type, check). This
// file is the contract between its three pieces:
//
//   director.ts        events -> beats (pure, tested)
//   three/agentTargets where each 3D part sits on screen, written per frame
//   AgentStage.tsx     plays the beats: flies the bot and cursor, draws the box
//
// DOM targets carry data-agent="<kind>:<id>" (see AgentTarget).

/** What a beat points at. */
export type AgentTarget =
  /** A part in the 3D viewport, by instance_id (screen rect from three/agentTargets). */
  | { kind: "part"; id: string }
  /** Any element with data-agent="<key>", e.g. "stage:board", "tab:code", "codetab:firmware", "row:<instance_id>", "decision:<id>", "check:<key>", "prompt", "viewport". */
  | { kind: "dom"; key: string };

/** How the bot acts a beat out. */
export type AgentAction =
  | "look" // glance at it, light box
  | "scan" // sweep a line across the box, top to bottom
  | "pick" // cursor clicks, ripple, box snaps tight
  | "drop" // box drops in from above with a squash, as a part lands
  | "trace" // a dashed path draws across the box (wiring, board routing)
  | "type" // a caret blinks in a small code chip next to the box
  | "check" // tick mark (or cross when bad) at the box corner
  | "cheer"; // done: bot hops, box glows

export interface Beat {
  /** Stable id, for keys and dedupe. */
  id: string;
  target: AgentTarget;
  action: AgentAction;
  /** Under 32 chars, shown on the selection box chip ("Placing ESP32-C3"). */
  label: string;
  /** Minimum time on this beat before the next one may start, in ms. */
  dwellMs: number;
  /** Something went wrong here (check fail, warning): red box, worried face. */
  bad?: boolean;
  /** UI the agent opens itself when this beat starts, so the panel follows the work. */
  open?: { rightTab?: "design" | "build" | "code"; codeTab?: "connections" | "board" | "firmware" };
}

/** Screen rect in client (viewport) pixels. */
export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** Agent on stage: on unless ?agent=0 (remembered). */
export function agentEnabled(): boolean {
  const q = new URLSearchParams(window.location.search).get("agent");
  if (q === "1" || q === "0") {
    try {
      localStorage.setItem("bara.agent", q);
    } catch {
      // storage blocked: the URL still decides for this page
    }
    return q === "1";
  }
  try {
    return localStorage.getItem("bara.agent") !== "0";
  } catch {
    return true;
  }
}
