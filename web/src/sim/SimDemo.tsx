// The bot demos the device: in simulation mode it flies onto the board, steers
// its cursor key to key and types through the real firmware (sim/api), then
// says what came out. Any touch from the user stops it and hands the board back.
import { useEffect, useRef, useState } from "react";
import { BaraBot } from "../bot/BaraBot";
import type { Emote, Mood } from "../bot/mood";
import { PRESETS, reducedMotion, Spring } from "../bot/spring";
import { simKeyFor, simKeys, simPress, simRelease, simSnapshot, simTap } from "./api";
import "./simDemo.css";

const BOT = 40;
const WORD = "hello";
/** Layer keys worth showing off, first match wins. */
const LAYER_KEYS = ["Lower", "Raise", "Fn", "Layer 1", "MO(1)"];

type Step = { kind: "say"; text: string; ms: number } | { kind: "tap"; id: string; hold?: string };

/** The script: type a word, a space, then one key on a held layer key. Keys the keymap lacks are skipped. */
export function demoScript(find: (label: string) => string | null): Step[] {
  const steps: Step[] = [{ kind: "say", text: "Let me try it out", ms: 900 }];
  for (const ch of WORD) {
    const id = find(ch.toUpperCase()) ?? find(ch);
    if (id) steps.push({ kind: "tap", id });
  }
  const space = find("Space") ?? find("Spc");
  if (space) steps.push({ kind: "tap", id: space });
  const layer = LAYER_KEYS.map(find).find((k): k is string => !!k);
  const one = find("1") ?? find("Q");
  if (layer && one) {
    steps.push({ kind: "say", text: "Now the layer key", ms: 800 });
    steps.push({ kind: "tap", id: one, hold: layer });
  }
  return steps;
}

function keyCentre(id: string): { x: number; y: number } | null {
  const r = simKeys().find((k) => k.id === id)?.rect;
  return r && r.width > 0 ? { x: r.left + r.width / 2, y: r.top + r.height / 2 } : null;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** Demo button plus the flying bot; mounted inside the simulation stage. */
export function SimDemo() {
  const [running, setRunning] = useState(false);
  const [say, setSay] = useState<{ text: string; n: number } | null>(null);
  const [mood, setMood] = useState<Mood>("working");
  const [emote, setEmote] = useState<{ kind: Emote; n: number } | null>(null);
  const botRef = useRef<HTMLDivElement>(null);
  const cursorRef = useRef<HTMLDivElement>(null);
  const rippleRef = useRef<HTMLDivElement>(null);
  const target = useRef({ x: 0, y: 0 });
  const abort = useRef(false);

  // Springs for the bot (floaty) and its cursor (gets there first), one rAF loop writing styles.
  useEffect(() => {
    if (!running) return;
    const start = { x: window.innerWidth - 120, y: 90 };
    target.current = start;
    const bx = new Spring(start.x, PRESETS.gentle);
    const by = new Spring(start.y, PRESETS.gentle);
    const cx = new Spring(start.x, PRESETS.smooth);
    const cy = new Spring(start.y, PRESETS.smooth);
    const instant = reducedMotion();
    let last = performance.now();
    let raf = 0;
    const tick = (now: number) => {
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      const t = target.current;
      cx.target = t.x;
      cy.target = t.y;
      // The bot hangs up and to the left of the key, out of the way of the legend.
      bx.target = t.x - BOT - 18;
      by.target = t.y - BOT - 14;
      for (const s of [bx, by, cx, cy]) {
        if (instant) s.value = s.target;
        else s.step(dt);
      }
      const lean = Math.max(-14, Math.min(14, bx.velocity * 0.02));
      if (botRef.current) botRef.current.style.transform = `translate(${bx.value}px, ${by.value}px) rotate(${lean}deg)`;
      if (cursorRef.current) cursorRef.current.style.transform = `translate(${cx.value}px, ${cy.value}px)`;
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [running]);

  // A touch from the user ends the demo.
  useEffect(() => {
    if (!running) return;
    const stop = (e: Event) => {
      if ((e.target as HTMLElement | null)?.closest?.(".sim-demo-btn")) return;
      abort.current = true;
    };
    window.addEventListener("pointerdown", stop, true);
    window.addEventListener("keydown", stop, true);
    return () => {
      window.removeEventListener("pointerdown", stop, true);
      window.removeEventListener("keydown", stop, true);
    };
  }, [running]);

  const run = async () => {
    abort.current = false;
    setRunning(true);
    setMood("working");
    let n = 0;
    const before = simSnapshot()?.text.length ?? 0;
    for (const step of demoScript(simKeyFor)) {
      if (abort.current) break;
      if (step.kind === "say") {
        setSay({ text: step.text, n: ++n });
        await sleep(step.ms);
        continue;
      }
      const at = keyCentre(step.id);
      if (at) target.current = at;
      await sleep(reducedMotion() ? 120 : 420);
      if (abort.current) break;
      const ripple = rippleRef.current;
      if (ripple && at) {
        ripple.style.transform = `translate(${at.x}px, ${at.y}px)`;
        ripple.classList.remove("on");
        void ripple.offsetWidth;
        ripple.classList.add("on");
      }
      setEmote({ kind: "pop", n: ++n });
      if (step.hold) {
        simPress(step.hold);
        await simTap(step.id, 110);
        simRelease(step.hold);
      } else await simTap(step.id, 90);
      await sleep(180);
    }
    const typed = (simSnapshot()?.text ?? "").slice(before).replace(/\s+/g, " ").trim();
    if (!abort.current) {
      setMood("happy");
      setEmote({ kind: "delight", n: ++n });
      setSay({ text: typed ? `It typed "${typed.slice(-24)}". Your turn!` : "Your turn!", n: ++n });
      await sleep(2600);
    }
    setRunning(false);
    setSay(null);
  };

  const keyboard = simKeys().length > 0;
  return (
    <>
      {keyboard && (
        <button type="button" className="sim-demo-btn btn" disabled={running} onClick={() => void run()} title="Watch the bot try the device">
          {running ? "Demoing…" : "Let the bot demo it"}
        </button>
      )}
      {running && (
        <div className="sim-demo" aria-hidden>
          <div ref={rippleRef} className="sim-demo-ripple" />
          <div ref={cursorRef} className="sim-demo-cursor">
            <svg width="18" height="20" viewBox="0 0 18 20">
              <path d="M1 1 L1 16 L5 12.5 L8 19 L11 17.6 L8 11.2 L13.5 11 Z" />
            </svg>
          </div>
          <div ref={botRef} className="sim-demo-bot">
            <BaraBot size={BOT} mood={mood} activity={mood === "working" ? "type" : null} emote={emote} say={say} bubbles />
          </div>
        </div>
      )}
    </>
  );
}
