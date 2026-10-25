// The agent in the landing replay: the same bot as the workspace, working the scene with an
// arrow cursor. The cursor goes where the replay points (BuildScene writes the aim every frame)
// and presses when it clicks; the bot floats just behind it, leaning into the moves, and says
// what it is doing in its small bubble. Position is springs (transform only); the bot's own face,
// blink and gaze are untouched. Under reduced motion it stands still beside the finished device.
import { useEffect, useMemo, useRef, useState, type MutableRefObject } from "react";
import { BaraBot, botBubbles } from "../bot/BaraBot";
import type { Activity, Emote } from "../bot/mood";
import { clamp, Spring, type SpringCfg } from "../bot/spring";

export interface AgentAim {
  x: number;
  y: number;
  pressing: boolean;
  set: boolean;
}

const BOT = 58;
const STEER: SpringCfg = { stiffness: 140, damping: 20 }; // the cursor: gets there first
const FLOAT: SpringCfg = { stiffness: 60, damping: 12 }; // the bot: floaty, trails the cursor

export function SceneAgent(props: { aim: MutableRefObject<AgentAim>; still: boolean; say: string | null; activity: Activity; done: boolean; hidden: boolean }) {
  const cursor = useRef<HTMLDivElement>(null);
  const ripple = useRef<HTMLDivElement>(null);
  const bot = useRef<HTMLDivElement>(null);
  const lean = useRef<HTMLDivElement>(null);
  const bubbles = useMemo(botBubbles, []);
  const n = useRef(0);
  const [say, setSay] = useState<{ text: string; n: number } | null>(null);
  const [emote, setEmote] = useState<{ kind: Emote; n: number } | null>(null);

  useEffect(() => {
    if (props.say) setSay({ text: props.say, n: ++n.current });
  }, [props.say]);
  useEffect(() => {
    if (props.done) setEmote({ kind: "delight", n: ++n.current });
  }, [props.done]);

  useEffect(() => {
    const cx = new Spring(0, STEER);
    const cy = new Spring(0, STEER);
    const bx = new Spring(0, FLOAT);
    const by = new Spring(0, FLOAT);
    const press = new Spring(1, { stiffness: 600, damping: 22 });
    let placed = false;
    let wasPressing = false;
    let raf = 0;
    let last = performance.now();
    const frame = (t: number) => {
      raf = requestAnimationFrame(frame);
      const dt = Math.min(0.05, (t - last) / 1000);
      last = t;
      const a = props.aim.current;
      if (!a.set) return;
      cx.target = a.x;
      cy.target = a.y;
      // the bot hovers up and to the left of its cursor, like a hand on a mouse
      bx.target = a.x - BOT * 0.95;
      by.target = a.y - BOT * 0.95;
      press.target = a.pressing ? 0.78 : 1;
      if (!placed || props.still) {
        for (const s of [cx, cy, bx, by]) {
          s.value = s.target;
          s.velocity = 0;
        }
        placed = true;
      } else {
        for (const s of [cx, cy, bx, by, press]) s.step(dt);
      }
      if (a.pressing && !wasPressing && ripple.current) {
        ripple.current.style.transform = `translate3d(${a.x}px, ${a.y}px, 0)`;
        ripple.current.classList.remove("on");
        void ripple.current.offsetWidth;
        ripple.current.classList.add("on");
      }
      wasPressing = a.pressing;
      if (cursor.current) cursor.current.style.transform = `translate3d(${cx.value.toFixed(1)}px, ${cy.value.toFixed(1)}px, 0) scale(${press.value.toFixed(3)})`;
      if (bot.current) bot.current.style.transform = `translate3d(${bx.value.toFixed(1)}px, ${by.value.toFixed(1)}px, 0)`;
      if (lean.current) lean.current.style.transform = `rotate(${clamp(bx.velocity * 0.03, -10, 10).toFixed(2)}deg)`;
    };
    raf = requestAnimationFrame(frame);
    return () => cancelAnimationFrame(raf);
  }, [props.aim, props.still]);

  return (
    <div className={`bs-agent ${props.hidden ? "is-hidden" : ""}`} aria-hidden>
      <div ref={bot} className="bs-bot">
        <div ref={lean} className="bs-bot-lean">
          <BaraBot size={BOT} mood={props.done ? "happy" : "working"} activity={props.activity} emote={emote} say={bubbles ? say : null} bubbles={bubbles} />
        </div>
      </div>
      <div ref={ripple} className="bs-ripple" />
      <div ref={cursor} className="bs-cursor">
        <svg viewBox="0 0 16 20" width="18" height="22">
          <path d="M1.5 1.5v15.2l4.1-3.9 2.7 6.1 2.6-1.1-2.7-6h5.7z" />
        </svg>
      </div>
    </div>
  );
}
