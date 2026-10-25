// The agent on the landing page: the same bot as the workspace, out in the open. It rests in the
// hero, slides to the prompt when you reach for it, leans in under an example chip you point at,
// and walks over to the demo to say what it is. Position is three springs (transform only); the
// bot's own face, blink and gaze are untouched. Under reduced motion it stays at home.
import { useEffect, useMemo, useRef, useState } from "react";
import { BaraBot, botBubbles } from "../bot/BaraBot";
import { clamp, PRESETS, reducedMotion, Spring } from "../bot/spring";
import { startListening, stopListening, useVoice } from "../voice/voice";

/** A press shorter than this is a tap (focus the prompt); a longer one talks. */
const HOLD_MS = 220;
const SAY_GAP_MS = 9000;
const PROMPT = ".ld-field .prompt-input";
/** The agent shrinks to this beside the chips so it never covers them. */
const CHIP_SCALE = 0.62;
const BIG = 172;
const SMALL = 88;

type Mode = "home" | "ask" | "chip" | "demo";

interface Spot {
  cx: number;
  cy: number;
  scale: number;
}

const LINES = {
  hello: "Tell me what you want to make.",
  ask: "I am listening.",
  demo: "This is a real build, played back.",
} as const;

export function LandingAgent() {
  const root = useRef<HTMLDivElement>(null);
  const lean = useRef<HTMLDivElement>(null);
  const bubbles = useMemo(botBubbles, []);
  const size = useRef(typeof window !== "undefined" && window.innerWidth < 600 ? SMALL : BIG);
  const [px, setPx] = useState(size.current);
  const [say, setSay] = useState<{ text: string; n: number } | null>(null);
  const [typing, setTyping] = useState(false);
  const [keys, setKeys] = useState(0);
  const [mode, setMode] = useState<Mode>("home");
  const [ready, setReady] = useState(false);
  const voiceOn = useVoice((s) => s.listening);
  const hold = useRef(0);

  useEffect(() => {
    const el = root.current;
    const box = el?.closest<HTMLElement>(".landing");
    if (!el || !box) return;
    const still = reducedMotion();
    const sx = new Spring(0, PRESETS.smooth);
    const sy = new Spring(0, PRESETS.smooth);
    const ss = new Spring(1, PRESETS.smooth);
    let placed = false;
    let armed = false; // the page's own autofocus does not count as the user reaching for the prompt
    let hoverChip: HTMLElement | null = null;
    let current: Mode = "home";
    let n = 0;
    const lastSaid: Record<string, number> = {};
    const speak = (key: keyof typeof LINES) => {
      const t = performance.now();
      if (t - (lastSaid[key] ?? -1e9) < SAY_GAP_MS) return;
      lastSaid[key] = t;
      setSay({ text: LINES[key], n: ++n });
    };
    const q = (s: string) => box.querySelector<HTMLElement>(s);

    const wantMode = (): Mode => {
      if (still) return "home";
      if (hoverChip && hoverChip.isConnected && spot("chip")) return "chip";
      const a = document.activeElement;
      if (armed && a instanceof HTMLElement && a.matches(PROMPT)) return "ask";
      const f = q(".ld-frame")?.getBoundingClientRect();
      // The recording is on the first screen, so the bot only walks onto it once the reader scrolls toward it.
      if (f && window.scrollY > 40) {
        const vis = Math.min(f.bottom, innerHeight) - Math.max(f.top, 0);
        if (vis > f.height * 0.5 && f.top < innerHeight * 0.55) return "demo";
      }
      return "home";
    };

    const spot = (m: Mode): Spot | null => {
      const c = box.getBoundingClientRect();
      const S = size.current;
      const rel = (r: DOMRect) => ({ l: r.left - c.left, t: r.top - c.top, b: r.bottom - c.top, w: r.width, h: r.height });
      const oval = 0.26; // half the oval's height, as a share of the bot box
      if (m === "chip" && hoverChip) {
        const r = rel(hoverChip.getBoundingClientRect());
        const f = q(".ld-field");
        const gutter = f ? f.getBoundingClientRect().left - c.left : 0;
        // out in the gutter beside the chip rows, level with the chip it is looking at
        if (gutter > S * CHIP_SCALE + 24) return { cx: gutter - 18 - (S * CHIP_SCALE) / 2, cy: r.t + r.h / 2, scale: CHIP_SCALE };
        return null;
      }
      if (m === "ask") {
        const bar = q(".ld-field .promptbar");
        if (bar) {
          const r = rel(bar.getBoundingClientRect());
          return { cx: r.l + 18 + S / 2, cy: r.t + 3 - oval * S, scale: 1 };
        }
      }
      if (m === "demo") {
        const fr = q(".ld-frame");
        if (fr) {
          const r = rel(fr.getBoundingClientRect());
          const floor = innerHeight - c.top - oval * S - 18;
          return { cx: r.l + 22 + S / 2, cy: Math.min(r.b - 22 - oval * S, floor), scale: 1 };
        }
      }
      // one slot per layout; the hidden one has no box
      const home = [...box.querySelectorAll<HTMLElement>(".ld-home")].find((h) => h.offsetParent !== null);
      if (!home) return null;
      const r = rel(home.getBoundingClientRect());
      // sits on the slot's floor, leaving its top for the speech bubble
      return { cx: r.l + S / 2, cy: r.b - 0.26 * S - 4, scale: 1 };
    };

    let raf = 0;
    let last = performance.now();
    const frame = (t: number) => {
      raf = requestAnimationFrame(frame);
      const dt = Math.min(0.05, (t - last) / 1000);
      last = t;
      const next = wantMode();
      if (next !== current) {
        current = next;
        setMode(next);
        if (next === "ask" || next === "demo") speak(next);
      }
      const s = spot(current);
      if (!s) return;
      const S = size.current;
      sx.target = s.cx - S / 2;
      sy.target = s.cy - S / 2;
      ss.target = s.scale;
      if (!placed || still) {
        sx.value = sx.target;
        sy.value = sy.target;
        ss.value = ss.target;
        sx.velocity = sy.velocity = ss.velocity = 0;
        if (!placed) {
          placed = true;
          setReady(true);
        }
      } else {
        sx.step(dt);
        sy.step(dt);
        ss.step(dt);
      }
      el.style.transform = `translate3d(${sx.value.toFixed(2)}px, ${sy.value.toFixed(2)}px, 0) scale(${ss.value.toFixed(3)})`;
      if (lean.current) lean.current.style.transform = `rotate(${(clamp(sx.velocity * 0.012, -9, 9) + (current === "chip" ? 7 : 0)).toFixed(2)}deg)`;
    };
    raf = requestAnimationFrame(frame);

    const onResize = () => {
      const S = window.innerWidth < 600 ? SMALL : BIG;
      if (S !== size.current) {
        size.current = S;
        setPx(S);
      }
    };
    const arm = () => {
      armed = true;
    };
    const onOver = (e: PointerEvent) => {
      hoverChip = e.target instanceof Element ? e.target.closest<HTMLElement>(".example-chip") : null;
    };
    const onFocusIn = (e: FocusEvent) => {
      if (e.target instanceof Element && e.target.matches(PROMPT)) setTyping(true);
    };
    const onFocusOut = (e: FocusEvent) => {
      if (e.target instanceof Element && e.target.matches(PROMPT)) setTyping(false);
    };
    const onInput = (e: Event) => {
      if (e.target instanceof Element && e.target.matches(PROMPT)) setKeys((k) => k + 1);
    };
    const hello = window.setTimeout(() => speak("hello"), 900);
    window.addEventListener("resize", onResize);
    window.addEventListener("keydown", arm, true);
    window.addEventListener("pointerdown", arm, true);
    window.addEventListener("pointerover", onOver, { passive: true });
    document.addEventListener("focusin", onFocusIn);
    document.addEventListener("focusout", onFocusOut);
    document.addEventListener("input", onInput);
    return () => {
      cancelAnimationFrame(raf);
      window.clearTimeout(hello);
      window.removeEventListener("resize", onResize);
      window.removeEventListener("keydown", arm, true);
      window.removeEventListener("pointerdown", arm, true);
      window.removeEventListener("pointerover", onOver);
      document.removeEventListener("focusin", onFocusIn);
      document.removeEventListener("focusout", onFocusOut);
      document.removeEventListener("input", onInput);
    };
  }, []);

  const focusPrompt = () => window.dispatchEvent(new CustomEvent("bara:focus-ask"));

  return (
    <div ref={root} className={`ld-agent ${ready ? "ready" : ""} m-${mode}`} style={{ width: px, height: px }}>
      <div ref={lean} className="ld-agent-lean">
        <button
          type="button"
          className="ld-agent-btn"
          aria-label="Bara. Tap to type your idea, hold to say it."
          title="Tap to type, hold to talk (or hold Space)"
          onPointerDown={(e) => {
            e.preventDefault();
            window.clearTimeout(hold.current);
            hold.current = window.setTimeout(() => {
              hold.current = 0;
              void startListening();
            }, HOLD_MS);
          }}
          onPointerUp={() => {
            if (hold.current) {
              window.clearTimeout(hold.current);
              hold.current = 0;
              focusPrompt();
            } else stopListening();
          }}
          onPointerLeave={() => {
            window.clearTimeout(hold.current);
            hold.current = 0;
            if (voiceOn) stopListening();
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              e.stopPropagation();
              focusPrompt();
            }
          }}
        >
          <span className="ld-agent-float">
            <BaraBot size={px} typing={typing} typingNonce={keys} bubbles={bubbles} say={say} />
          </span>
        </button>
      </div>
    </div>
  );
}
