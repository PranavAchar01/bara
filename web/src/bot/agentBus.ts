// Side door into the agent on stage. The build drives it through the event log
// (director.ts); everything else (explaining a part, acting out an ask, the
// candidate fly-by, replays) asks it to do things here. AgentStage.tsx is the
// only listener: it plays requests through the same queue, flying out from the
// prompt bar when it is home and back when the request is played out.
import type { Beat, Rect } from "./agent";

export interface AgentRequest {
  /** Who asked, for dedupe and debugging ("explain", "ask", "flyby", "replay"). */
  source: string;
  beats: Beat[];
  /** Drop whatever is queued and start on these now (hover explanations). */
  interrupt?: boolean;
  /** One line the bot says as the first beat starts (under 60 chars). */
  say?: string;
}

type Listener = (r: AgentRequest) => void;
const listeners = new Set<Listener>();

/** Ask the agent to do something. A no-op when the stage is not mounted or is turned off. */
export function agentDo(r: AgentRequest): void {
  for (const l of listeners) l(r);
}

/** AgentStage subscribes here. */
export function onAgentDo(l: Listener): () => void {
  listeners.add(l);
  return () => {
    listeners.delete(l);
  };
}

let pos: Rect | null = null;

/** Where the stage bot is on screen right now (client px), or null when it is home. AgentStage writes it every frame. */
export function agentPos(): Rect | null {
  return pos;
}

export function setAgentPos(r: Rect | null): void {
  pos = r;
}
