// "The bot is thinking": when the build compares options for a slot, a few
// option cards fan out next to the bot, the highlight flashes through them,
// the losers drop away and the chosen one pops, gets a tick and shrinks into
// its parts list row. Pure decisions live in flyby.ts; this only animates.
// Decorative: never takes a click, hidden from assistive tech (the build tab
// already lists the candidates and the decision).
import { type CSSProperties, useEffect, useRef, useState } from "react";
import { useApp } from "../state/store";
import { agentEnabled } from "./agent";
import { agentPos } from "./agentBus";
import { reducedMotion } from "./spring";
import {
  cardsFor,
  envelopeOf,
  FlybyTracker,
  type FlyCard,
  type FlyItem,
  type FlyPlan,
  PART_WAIT_MS,
  planFor,
  seedOf,
  shuffleSequence,
} from "./flyby";
import "./candidateFlyby.css";

const CARD_W = 184;
const CARD_H = 46;
const GAP = 6;
const MARGIN = 8;
const BOT_GAP = 14;
/** One flash of the shuffle highlight. */
const STEP_MS = 120;

type Phase = "enter" | "fan" | "shuffle" | "settle" | "fly" | "fade";

interface Show {
  item: FlyItem;
  plan: FlyPlan;
  cards: FlyCard[];
  winner: number;
  phase: Phase;
}

export function CandidateFlyby() {
  const [on] = useState(agentEnabled);
  const [show, setShow] = useState<Show | null>(null);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const cardRefs = useRef<(HTMLDivElement | null)[]>([]);
  // What the frame loop reads: the current show, the shuffle clock and sequence.
  const live = useRef<{ show: Show | null; shuffleAt: number; seq: number[]; hot: number }>({ show: null, shuffleAt: 0, seq: [], hot: -1 });

  // Event stream -> queue of fly-bys, played one at a time on timers.
  useEffect(() => {
    if (!on) return;
    const state = live.current;
    const tracker = new FlybyTracker();
    const queue: FlyItem[] = [];
    const timers = new Set<number>();
    let busy = false;
    let seen = useApp.getState().log.at(-1)?.id ?? 0;

    const at = (ms: number, fn: () => void) => {
      const id = window.setTimeout(() => {
        timers.delete(id);
        fn();
      }, ms);
      timers.add(id);
    };
    const set = (s: Show | null) => {
      live.current.show = s;
      setShow(s);
    };
    const phase = (p: Phase) => {
      const cur = live.current.show;
      if (cur) set({ ...cur, phase: p });
    };

    const next = () => {
      const item = queue.shift();
      if (!item) {
        busy = false;
        set(null);
        return;
      }
      busy = true;
      const reduced = reducedMotion();
      const plan = planFor(item, queue.length, reduced);
      const { cards, winner } = cardsFor(item, plan.mode);
      const steps = plan.shuffleMs > 0 ? Math.max(3, Math.round(plan.shuffleMs / STEP_MS)) : 0;
      live.current.seq = shuffleSequence(cards.length, winner, steps, seedOf(item.key));
      live.current.hot = -1;
      cardRefs.current = [];
      const s: Show = { item, plan, cards, winner, phase: plan.mode === "static" ? "settle" : "enter" };
      set(s);

      let t = 0;
      if (plan.mode !== "static") {
        // Let the cards paint stacked on the bot before they fan out.
        at(40, () => phase("fan"));
        t = 40 + plan.fanMs;
        if (plan.shuffleMs > 0) {
          at(t, () => {
            live.current.shuffleAt = performance.now();
            phase("shuffle");
          });
          t += plan.shuffleMs;
        }
        at(t, () => phase("settle"));
      }
      t += plan.settleMs;
      at(t, () => exit(item, plan, winner, reduced, performance.now()));
    };

    // The chosen card flies into its row once its part.added is in; otherwise it waits (only while nothing is queued) and then fades.
    const exit = (item: FlyItem, plan: FlyPlan, winner: number, reduced: boolean, since: number) => {
      const instance = tracker.instanceFor(item.winnerPartId);
      if (winner >= 0 && !instance && !queue.length && performance.now() - since < PART_WAIT_MS) {
        at(100, () => exit(item, plan, winner, reduced, since));
        return;
      }
      const card = cardRefs.current[winner];
      const row = instance ? document.querySelector<HTMLElement>(`[data-agent="row:${CSS.escape(instance)}"]`) : null;
      const rr = row?.getBoundingClientRect();
      const onScreen = rr && rr.width > 0 && rr.height > 0 && rr.bottom > 0 && rr.top < window.innerHeight;
      if (!reduced && card && rr && onScreen) {
        const cr = card.getBoundingClientRect();
        const dx = rr.left + Math.min(rr.width, 160) / 2 - (cr.left + cr.width / 2);
        const dy = rr.top + rr.height / 2 - (cr.top + cr.height / 2);
        card.style.transform = `translate(${dx.toFixed(1)}px, ${dy.toFixed(1)}px) scale(0.28)`;
        card.style.opacity = "0";
        phase("fly");
      } else {
        phase("fade");
      }
      at(plan.exitMs, next);
    };

    const unsub = useApp.subscribe((st) => {
      const fresh = st.log.filter((e) => e.id > seen && e.dir === "in" && (!e.buildId || e.buildId === st.build?.build_id));
      seen = st.log.at(-1)?.id ?? seen;
      if (!fresh.length) return;
      for (const e of fresh) {
        const env = envelopeOf(e.raw);
        const item = tracker.feed(e.type, env.payload, env.seq ?? e.seq);
        if (item) queue.push(item);
      }
      if (!busy && queue.length) next();
    });
    return () => {
      unsub();
      for (const id of timers) clearTimeout(id);
      timers.clear();
      state.show = null;
    };
  }, [on]);

  // One frame loop while cards are up: follow the bot, keep the stack on screen, flash the shuffle.
  const visible = show !== null;
  useEffect(() => {
    if (!visible) return;
    let raf = 0;
    const tick = () => {
      raf = requestAnimationFrame(tick);
      const s = live.current.show;
      const wrap = wrapRef.current;
      if (!s || !wrap) return;
      if (s.phase !== "fly") place(wrap, s.cards.length);
      if (s.phase === "shuffle") {
        const seq = live.current.seq;
        const k = seq[Math.min(seq.length - 1, Math.floor((performance.now() - live.current.shuffleAt) / STEP_MS))] ?? -1;
        if (k !== live.current.hot) {
          live.current.hot = k;
          cardRefs.current.forEach((el, i) => el?.toggleAttribute("data-hot", i === k));
        }
      } else if (live.current.hot !== -1) {
        live.current.hot = -1;
        cardRefs.current.forEach((el) => el?.removeAttribute("data-hot"));
      }
    };
    tick();
    return () => cancelAnimationFrame(raf);
  }, [visible]);

  if (!on || !show) return null;
  const { cards, winner, phase, plan, item } = show;
  return (
    <div key={item.key} ref={wrapRef} className="cflyby" data-phase={phase} data-mode={plan.mode} aria-hidden="true">
      {cards.map((c, i) => {
        const top = i * (CARD_H + GAP);
        const style = { top, "--i": i, "--top": `${top}px`, "--rot": i % 2 ? "3deg" : "-4deg" } as CSSProperties;
        return (
          <div
            key={c.partId}
            ref={(el) => {
              cardRefs.current[i] = el;
            }}
            className="cf-card"
            data-win={i === winner ? "" : undefined}
            style={style}
          >
            <div className="cf-row">
              <span className="cf-name">{c.name}</span>
              {c.kind && <span className="cf-kind">{c.kind}</span>}
            </div>
            {c.specs && <div className="cf-specs">{c.specs}</div>}
            {c.score != null && (
              <div className="cf-score">
                <i style={{ width: `${Math.round(c.score * 100)}%` }} />
              </div>
            )}
            {i === winner && (
              <span className="cf-tick">
                <svg viewBox="0 0 12 12" width="10" height="10">
                  <path d="M2.5 6.4 5 8.8 9.6 3.6" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}

/** Puts the stack beside the stage bot (or above the docked one when it is home), on screen. */
function place(wrap: HTMLDivElement, n: number) {
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const stackH = n * CARD_H + Math.max(0, n - 1) * GAP;
  let x: number;
  let y: number;
  let cx: number;
  let cy: number;
  const r = agentPos();
  if (r) {
    cx = r.x + r.w / 2;
    cy = r.y + r.h / 2;
    x = r.x + r.w + BOT_GAP;
    if (x + CARD_W > vw - MARGIN) x = r.x - BOT_GAP - CARD_W;
    y = cy - stackH / 2;
  } else {
    const home = document.querySelector<HTMLElement>(".prompt-bot")?.getBoundingClientRect();
    if (home && home.width > 0) {
      cx = home.left + home.width / 2;
      cy = home.top + home.height / 2;
      x = cx - CARD_W / 2;
      y = home.top - BOT_GAP - stackH;
    } else {
      cx = vw / 2;
      cy = vh - 60;
      x = cx - CARD_W / 2;
      y = cy - BOT_GAP - stackH;
    }
  }
  x = Math.min(Math.max(MARGIN, x), Math.max(MARGIN, vw - CARD_W - MARGIN));
  y = Math.min(Math.max(MARGIN, y), Math.max(MARGIN, vh - stackH - MARGIN));
  wrap.style.transform = `translate3d(${x.toFixed(1)}px, ${y.toFixed(1)}px, 0)`;
  wrap.style.setProperty("--ox", `${(cx - x).toFixed(1)}px`);
  wrap.style.setProperty("--oy", `${(cy - y).toFixed(1)}px`);
}
