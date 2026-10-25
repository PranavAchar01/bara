// The handoff from the landing into the workspace. When a build starts from the intro or the Build pop-up,
// the page does not cut: the bot and the prompt glide to where the workspace shows them while the workspace
// fades and scales in behind. Armed by the sender (with where things were), played once the workspace is on screen.
import { useLayoutEffect, useRef, useState } from "react";
import { create } from "zustand";
import { reducedMotion } from "../bot/spring";

interface Armed {
  /** The bot's body (the intro's oval) when the sender had one. */
  bot: DOMRect | null;
  field: DOMRect;
  text: string;
  at: number;
}

const useHandoff = create<{ armed: Armed | null }>(() => ({ armed: null }));
const FRESH_MS = 20_000;
const HANDOFF_MS = 800;

/** Remembers where the prompt (and the bot) are, to be handed to the workspace when it appears. */
export function armHandoff(text: string, field: Element | null, bot: Element | null): void {
  if (!field || reducedMotion()) return;
  const r = bot?.getBoundingClientRect();
  // the intro's box is square; the oval sits in the middle of it (88 × 62 of 120)
  const oval = r ? new DOMRect(r.left + (r.width * 16) / 120, r.top + (r.height * 29) / 120, (r.width * 88) / 120, (r.height * 62) / 120) : null;
  useHandoff.setState({ armed: { bot: oval, field: field.getBoundingClientRect(), text, at: Date.now() } });
}

/** True while the handoff plays, so the workspace can fade in behind it. */
export function useHandoffRunning(): boolean {
  return useRunning((s) => s.run !== null);
}
const useRunning = create<{ run: Armed | null }>(() => ({ run: null }));

/** Bara's body: the ink oval with two eyes. Drawn in code, scales with its box. */
export function BaraMark(props: { className?: string }) {
  return (
    <svg className={props.className} viewBox="0 0 88 62" aria-hidden>
      <rect width="88" height="62" rx="31" fill="currentColor" />
      <rect x="25" y="21.5" width="13" height="19" rx="6.5" fill="var(--paper)" />
      <rect x="50" y="21.5" width="13" height="19" rx="6.5" fill="var(--paper)" />
    </svg>
  );
}

const box = (r: DOMRect) => ({ left: `${r.left}px`, top: `${r.top}px`, width: `${r.width}px`, height: `${r.height}px` });

/** Mounted once, in the app. Plays when the workspace appears for an armed build. */
export function Handoff(props: { screen: string }) {
  const armed = useHandoff((s) => s.armed);
  const run = useRunning((s) => s.run);
  const layer = useRef<HTMLDivElement>(null);
  const bot = useRef<HTMLDivElement>(null);
  const field = useRef<HTMLDivElement>(null);
  const [, tick] = useState(0);

  useLayoutEffect(() => {
    if (props.screen !== "workspace" || !armed) return;
    useHandoff.setState({ armed: null });
    if (Date.now() - armed.at > FRESH_MS || reducedMotion()) return;
    useRunning.setState({ run: armed });
    tick((n) => n + 1);
  }, [props.screen, armed]);

  useLayoutEffect(() => {
    if (!run) return;
    // where the workspace shows the prompt: the docked bar, or the starting card while the build has not begun
    const dock = document.querySelector(".centre-bottom .promptbar") ?? document.querySelector(".canvas-starting");
    const to = dock?.getBoundingClientRect() ?? new DOMRect(run.field.left, window.innerHeight - 90, run.field.width, 48);
    const ease = "cubic-bezier(0.65, 0, 0.2, 1)";
    const opts = { duration: HANDOFF_MS, easing: ease, fill: "forwards" as const };
    const anims: Animation[] = [];
    anims.push(layer.current!.animate([{ opacity: 1 }, { opacity: 1, offset: 0.25 }, { opacity: 0 }], { duration: HANDOFF_MS, easing: "ease-out", fill: "forwards" }));
    const f = field.current;
    if (f) {
      const target = { left: to.left, top: to.top, width: Math.min(to.width, run.field.width), height: Math.min(to.height, 52) };
      target.left = to.left + (to.width - target.width) / 2;
      anims.push(f.animate([{ ...box(run.field), opacity: 1 }, { ...box(new DOMRect(target.left, target.top, target.width, target.height)), opacity: 1, offset: 0.7 }, { ...box(new DOMRect(target.left, target.top, target.width, target.height)), opacity: 0 }], opts));
    }
    const b = bot.current;
    if (b) {
      const from = run.bot ?? new DOMRect(run.field.left + 6, run.field.top + run.field.height / 2 - 11, 36, 25);
      const w = 30;
      const h = (w * 62) / 88;
      const to2 = new DOMRect(to.left + 14, to.top + (to.height - h) / 2, w, h);
      anims.push(b.animate([{ ...box(from), opacity: 1 }, { ...box(to2), opacity: 1, offset: 0.8 }, { ...box(to2), opacity: 0 }], opts));
    }
    const t = window.setTimeout(() => useRunning.setState({ run: null }), HANDOFF_MS + 40);
    return () => {
      window.clearTimeout(t);
      anims.forEach((a) => a.cancel());
    };
  }, [run]);

  if (!run) return null;
  const botBox = run.bot ? box(run.bot) : undefined;
  return (
    <div className="ho" aria-hidden>
      <div ref={layer} className="ho-layer" />
      <div ref={field} className="ho-field" style={box(run.field)}>
        <span>{run.text}</span>
      </div>
      <div ref={bot} className="ho-bot" style={botBox}>
        <BaraMark />
      </div>
    </div>
  );
}
