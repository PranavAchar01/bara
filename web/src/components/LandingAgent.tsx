// The agent in the landing replay: the same bot as the workspace, doing the work in the mock
// itself. It flies to the part tray, takes a part in its hands, carries it to the board, sets it
// down, clicks Route, steps aside to watch the case close and reacts. An arrow cursor is its
// pointer: it goes where the replay points (BuildScene writes the aim every frame) and presses
// when it clicks; the bot floats beside it, bobbing, leaning into its moves and stretching a
// little at speed. Position is springs (transform only); the bot's own face, blink and gaze are
// untouched. Under reduced motion it stands still beside the finished device.
import { useEffect, useMemo, useRef, useState, type MutableRefObject } from "react";
import { BaraBot, botBubbles } from "../bot/BaraBot";
import type { Activity, Emote } from "../bot/mood";
import { clamp, Spring, type SpringCfg } from "../bot/spring";
import type { Carried } from "../library/replayTimeline";

export interface AgentAim {
  x: number;
  y: number;
  pressing: boolean;
  set: boolean;
  /** Hover below and to the right of the pointer instead of above and to the left (near the top edge). */
  peek?: boolean;
  /** Which side of the pointer the bot floats on: -1 left (default), 1 right, so it keeps clear of the middle. */
  side?: -1 | 1;
  /** Size of the area the agent works in, to keep the bot inside it. */
  w?: number;
  h?: number;
}

const BOT = 124;
const STEER: SpringCfg = { stiffness: 170, damping: 22 }; // the pointer: gets there first
const FLOAT: SpringCfg = { stiffness: 95, damping: 13 }; // the bot: floaty, a little overshoot

export const CARRY_FILL: Record<string, string> = {
  mcu: "#2e2e2e",
  screen: "#3a3f45",
  switch: "#d6d6d6",
  encoder: "#9aa0a6",
  joystick: "#4a4a4a",
  button: "#f2f2f0",
  speaker: "#6b6b6b",
};

export function SceneAgent(props: {
  aim: MutableRefObject<AgentAim>;
  still: boolean;
  activity: Activity;
  done: boolean;
  hidden: boolean;
  carry: Carried | null;
  beat: { kind: Emote; n: number } | null;
}) {
  const cursor = useRef<HTMLDivElement>(null);
  const ripple = useRef<HTMLDivElement>(null);
  const bot = useRef<HTMLDivElement>(null);
  const lean = useRef<HTMLDivElement>(null);
  const shadow = useRef<HTMLDivElement>(null);
  const bubbles = useMemo(botBubbles, []);
  const n = useRef(0);
  const [emote, setEmote] = useState<{ kind: Emote; n: number } | null>(null);

  useEffect(() => {
    if (props.beat) setEmote(props.beat);
  }, [props.beat]);
  useEffect(() => {
    if (props.done) setEmote({ kind: "delight", n: ++n.current + 1000 });
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
      // the bot hovers up and to the left of its pointer, like a hand on a mouse; near the top edge it
      // drops below and to the right so it never leaves the window
      let tx = a.peek || a.side === 1 ? a.x + 4 : a.x - BOT * 0.82;
      let ty = a.peek ? a.y + 8 : a.y - BOT * 0.85;
      if (a.w && a.h) {
        tx = clamp(tx, 2, a.w - BOT - 2);
        ty = clamp(ty, 2, a.h - BOT - 2);
      }
      bx.target = tx;
      by.target = ty;
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
      const bob = props.still ? 0 : Math.sin(t / 310) * 2.6;
      const speed = Math.hypot(bx.velocity, by.velocity);
      const stretch = props.still ? 0 : Math.min(0.1, speed / 5200);
      if (cursor.current) cursor.current.style.transform = `translate3d(${cx.value.toFixed(1)}px, ${cy.value.toFixed(1)}px, 0) scale(${press.value.toFixed(3)})`;
      if (bot.current) bot.current.style.transform = `translate3d(${bx.value.toFixed(1)}px, ${(by.value + bob).toFixed(1)}px, 0)`;
      if (lean.current) lean.current.style.transform = `rotate(${clamp(bx.velocity * 0.03, -11, 11).toFixed(2)}deg) scale(${(1 + stretch).toFixed(3)}, ${(1 - stretch).toFixed(3)})`;
      if (shadow.current) {
        const lift = clamp(bob / 2.6, -1, 1);
        shadow.current.style.transform = `translate3d(${(bx.value + BOT / 2 - 32).toFixed(1)}px, ${(by.value + BOT * 0.88).toFixed(1)}px, 0) scale(${(1 - lift * 0.06 - stretch).toFixed(3)}, 1)`;
      }
    };
    raf = requestAnimationFrame(frame);
    return () => cancelAnimationFrame(raf);
  }, [props.aim, props.still]);

  return (
    <div className={`bs-agent ${props.hidden ? "is-hidden" : ""} ${props.done ? "is-happy" : ""}`} aria-hidden>
      <div ref={shadow} className="bs-shadow" />
      <div ref={bot} className={`bs-bot ${props.carry ? "carrying" : ""}`}>
        <div ref={lean} className="bs-bot-lean">
          <BaraBot size={BOT} mood={props.done ? "happy" : "working"} activity={props.activity} emote={emote} say={null} bubbles={bubbles} />
          <span className="bs-hand l" />
          <span className="bs-hand r" />
        </div>
        {props.carry && (
          <span key={props.carry.label} className="bs-carry">
            <i style={{ background: CARRY_FILL[props.carry.role] ?? "#e4e4e4" }} />
            {props.carry.count > 1 ? `${props.carry.count} × ` : ""}
            {props.carry.label}
          </span>
        )}
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
