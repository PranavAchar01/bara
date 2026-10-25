// The landing's one control and what it opens. The hero shows a Build button made of Bara's own body: an
// ink stadium whose two small eyes follow the pointer, so it is plainly alive and not part of the recording
// behind it. Pressing it (or just starting to type) washes the page to paper from the button outward while
// the button glides to the middle and becomes Bara, who perks up and asks what's up, out loud when it can.
// Then it listens: just answer, and a pause sends it (or hold Space, or type; typing takes over the mic).
// Ideas type themselves into the empty field.
import { useEffect, useLayoutEffect, useRef, useState, type FormEvent } from "react";
import { createPortal } from "react-dom";
import { BaraBot } from "../bot/BaraBot";
import { reducedMotion } from "../bot/spring";
import type { Emote, Mood } from "../bot/mood";
import { routePrompt } from "../net/client";
import { demoPrompts } from "../spec/fixtures";
import { useApp } from "../state/store";
import { Icon } from "../ui/common";
import { armHandoff } from "./Handoff";
import { cancelListening, micAllowed, speak, startListening, stopListening, stopSpeaking, useVoice } from "../voice/voice";

const IDEAS = ["a macropad with one big knob", "a wireless split keyboard with an OLED", "a 60% keyboard with Choc switches", "something cool for my desk"];
/** What Bara says when it arrives: a different hello each time, so it never sounds canned. Short
 *  enough to sit on one line under Bara on a laptop screen. */
const GREETINGS = ["Hey! What's the idea?", "Oh hi! What's new?", "Hey you! Got an idea?", "Hi! Ooh, what's next?"];
let greeted = Math.floor(Math.random() * GREETINGS.length);
const nextGreeting = () => GREETINGS[greeted++ % GREETINGS.length];
const TYPE_MS = 45;
const SHOW_MS = 2400;
/** The wash and the glide, in ms. */
const WASH_MS = 720;
const GLIDE_MS = 780;
/** Bara's oval and eyes, in its 120-unit viewBox (bot/BaraBot.tsx). */
const OVAL = { w: 88, h: 62 };
const EYES = { span: 38, h: 19 }; // two 13-wide eyes 25 apart, outer edge to outer edge

/** The idea being typed out in an empty field, letter by letter, then rubbed out for the next. */
function useIdeaGhost(on: boolean): { ghost: string; idea: string } {
  const [ideas, setIdeas] = useState(IDEAS);
  const [i, setI] = useState(0);
  const [len, setLen] = useState(0);
  useEffect(() => {
    let live = true;
    void demoPrompts().then((p) => {
      const fromStreams = p.map((x) => x.prompt).filter((x) => x.length < 48);
      if (live && fromStreams.length) setIdeas([...new Set([...fromStreams, ...IDEAS])]);
    });
    return () => {
      live = false;
    };
  }, []);
  const idea = ideas[i % ideas.length];
  useEffect(() => {
    if (!on) return;
    if (reducedMotion()) {
      setLen(idea.length);
      const t = window.setTimeout(() => setI((v) => v + 1), SHOW_MS * 2);
      return () => window.clearTimeout(t);
    }
    if (len < idea.length) {
      const t = window.setTimeout(() => setLen((v) => v + 1), TYPE_MS);
      return () => window.clearTimeout(t);
    }
    const t = window.setTimeout(() => {
      setLen(0);
      setI((v) => v + 1);
    }, SHOW_MS);
    return () => window.clearTimeout(t);
  }, [on, len, idea]);
  return { ghost: idea.slice(0, len), idea };
}

/** How the intro was opened: from where, and with what already typed. */
export interface IntroOpen {
  from: DOMRect;
  seed: string;
}

/** The hero's Build button. Its eyes watch the pointer and blink; a slow halo breathes around it. */
export function HeroCta(props: { onOpen: (o: IntroOpen) => void; hidden: boolean }) {
  const btn = useRef<HTMLButtonElement>(null);
  const eyes = useRef<HTMLSpanElement>(null);
  const ready = useApp((s) => s.hello !== null);
  const open = (seed = "") => {
    if (btn.current) props.onOpen({ from: btn.current.getBoundingClientRect(), seed });
  };
  const openRef = useRef(open);
  openRef.current = open;

  // The eyes look toward the pointer, a couple of pixels at most. At most one write per frame, and the
  // eyes' centre is measured only after a scroll or resize, so moving the mouse never forces a layout.
  useEffect(() => {
    let centre: { x: number; y: number } | null = null;
    let at: { x: number; y: number } | null = null;
    let raf = 0;
    const stale = () => (centre = null);
    const paint = () => {
      raf = 0;
      const el = eyes.current;
      if (!el || !at) return;
      if (!centre) {
        const r = el.getBoundingClientRect();
        centre = { x: r.left + r.width / 2, y: r.top + r.height / 2 };
      }
      const dx = at.x - centre.x;
      const dy = at.y - centre.y;
      const d = Math.hypot(dx, dy) || 1;
      const k = Math.min(1, d / 240);
      el.style.setProperty("--look-x", `${((dx / d) * 2.2 * k).toFixed(2)}px`);
      el.style.setProperty("--look-y", `${((dy / d) * 1.6 * k).toFixed(2)}px`);
    };
    const move = (e: PointerEvent) => {
      at = { x: e.clientX, y: e.clientY };
      if (!raf) raf = requestAnimationFrame(paint);
    };
    window.addEventListener("pointermove", move, { passive: true });
    window.addEventListener("scroll", stale, { passive: true });
    window.addEventListener("resize", stale);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("pointermove", move);
      window.removeEventListener("scroll", stale);
      window.removeEventListener("resize", stale);
    };
  }, []);

  // Typing anywhere (or Enter) opens the intro with what was typed already in the field.
  useEffect(() => {
    if (props.hidden) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable)) return;
      const printable = e.key.length === 1 && e.key !== " ";
      if (!printable && !(e.key === "Enter" && t === document.body)) return;
      // the voice keys (V) would otherwise read this letter as a shortcut
      e.preventDefault();
      e.stopPropagation();
      openRef.current(printable ? e.key : "");
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [props.hidden]);

  return (
    <button ref={btn} type="button" className={`hero-cta ${props.hidden ? "is-away" : ""}`} onClick={() => open()} disabled={!ready} aria-label="Start building with Bara">
      <span ref={eyes} className="cta-eyes" aria-hidden>
        <i />
        <i />
      </span>
      <span className="cta-label">Start building</span>
      <span className="cta-go" aria-hidden>
        <Icon name="send" size={14} />
      </span>
    </button>
  );
}

type Phase = "wash" | "here" | "leaving";

/** The paper wash, the button becoming Bara, and Bara asking what's up. */
export function AgentIntro(props: { open: IntroOpen; onClose: () => void }) {
  const { from, seed } = props.open;
  const still = reducedMotion();
  const [phase, setPhase] = useState<Phase>(still ? "here" : "wash");
  const [greeting] = useState(nextGreeting);
  const [text, setText] = useState(seed);
  const [asked, setAsked] = useState(still ? greeting : "");
  const [emote, setEmote] = useState<{ kind: Emote; n: number } | null>(null);
  const [keys, setKeys] = useState(0);
  const wash = useRef<HTMLDivElement>(null);
  const morph = useRef<HTMLDivElement>(null);
  const morphEyes = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const ready = useApp((s) => s.hello !== null && (s.conn === "open" || s.conn === "resyncing"));
  const conn = useApp((s) => s.conn);
  const pending = useApp((s) => s.pendingStart !== null);
  const maxChars = useApp((s) => s.hello?.limits?.max_prompt_chars ?? 2000);
  const listening = useVoice((s) => s.listening);
  const heard = useVoice((s) => s.heard);
  const transcribing = useVoice((s) => s.transcribing);
  const thinking = useVoice((s) => s.thinking);
  const voiceMode = useVoice((s) => s.mode);
  const voiceError = useVoice((s) => s.error);
  const { ghost, idea } = useIdeaGhost(phase === "here" && !text && !listening && !transcribing && !pending);

  // Where Bara lands: the middle, a little high, at a size that suits the screen.
  const size = Math.round(Math.min(220, Math.max(140, window.innerWidth * 0.14)));
  const cx = window.innerWidth / 2;
  const cy = Math.min(window.innerHeight * 0.36, window.innerHeight / 2 - 60);
  const unit = size / 120;
  const oval = { w: OVAL.w * unit, h: OVAL.h * unit };
  const fx = from.left + from.width / 2;
  const fy = from.top + from.height / 2;
  const reach = Math.hypot(Math.max(fx, window.innerWidth - fx), Math.max(fy, window.innerHeight - fy));

  const emoteNow = (kind: Emote) => setEmote((e) => ({ kind, n: (e?.n ?? 0) + 1 }));

  // The page is held still while the intro is up.
  useEffect(() => {
    const html = document.documentElement;
    const was = html.style.overflow;
    html.style.overflow = "hidden";
    return () => {
      html.style.overflow = was;
      // only the intro's own greeting: the intro also closes because a build started, and what the
      // build says (a question for you, and the mic it hands back) must carry on. Back (close) stops all.
      if (useVoice.getState().caption === greeting) stopSpeaking();
    };
  }, [greeting]);

  // Wash out from the button; the button glides to the middle as it turns into Bara.
  useLayoutEffect(() => {
    if (still) return;
    const ease = "cubic-bezier(0.65, 0, 0.35, 1)";
    wash.current?.animate([{ clipPath: `circle(0px at ${fx}px ${fy}px)` }, { clipPath: `circle(${reach}px at ${fx}px ${fy}px)` }], { duration: WASH_MS, easing: ease, fill: "forwards" });
    const eyesFrom = from.height * 0.36; // the button's eye box height (see .cta-eyes)
    morph.current?.animate(
      [
        { left: `${from.left}px`, top: `${from.top}px`, width: `${from.width}px`, height: `${from.height}px` },
        { left: `${cx - oval.w / 2}px`, top: `${cy - oval.h / 2}px`, width: `${oval.w}px`, height: `${oval.h}px` },
      ],
      { duration: GLIDE_MS, easing: "cubic-bezier(0.5, 0, 0.2, 1.15)", fill: "forwards" },
    );
    const cta = document.querySelector<HTMLElement>(".hero-cta .cta-eyes")?.getBoundingClientRect();
    morphEyes.current?.animate(
      [
        cta
          ? { left: `${cta.left - from.left}px`, top: `${cta.top - from.top}px`, width: `${cta.width}px`, height: `${cta.height}px` }
          : { left: "16px", top: `${(from.height - eyesFrom) / 2}px`, width: `${eyesFrom * 2}px`, height: `${eyesFrom}px` },
        { left: `${(oval.w - EYES.span * unit) / 2}px`, top: `${(oval.h - EYES.h * unit) / 2}px`, width: `${EYES.span * unit}px`, height: `${EYES.h * unit}px` },
      ],
      { duration: GLIDE_MS, easing: "cubic-bezier(0.5, 0, 0.2, 1.15)", fill: "forwards" },
    );
    const t = window.setTimeout(() => setPhase("here"), GLIDE_MS);
    return () => window.clearTimeout(t);
    // the opening is played once, from where it was opened
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Arrived: a little surprise, a hop, then the question, typed and (when it can) said.
  useEffect(() => {
    if (phase !== "here") return;
    const timers: number[] = [];
    const at = (ms: number, fn: () => void) => timers.push(window.setTimeout(fn, ms));
    if (!still) {
      emoteNow("surprise");
      at(380, () => emoteNow("hop"));
      at(760, () => emoteNow("delight"));
      for (let i = 1; i <= greeting.length; i++) at(420 + i * 38, () => setAsked(greeting.slice(0, i)));
    }
    // voice first: once it has asked, it listens for the answer, when the mic is already allowed
    // (never a permission prompt out of nowhere) and nothing has been typed yet
    const listen = () => {
      if (!input.current?.value) void micAllowed().then((ok) => {
          if (ok && !input.current?.value) void startListening("auto");
        });
    };
    at(still ? 0 : 420, () => speak(greeting, true, listen, "greeting"));
    at(still ? 0 : 900, () => input.current?.focus({ preventScroll: true }));
    return () => timers.forEach((t) => window.clearTimeout(t));
  }, [phase, still, greeting]);

  const close = () => {
    if (phase === "leaving") return;
    stopSpeaking();
    if (useVoice.getState().listening) cancelListening();
    if (still) return props.onClose();
    setPhase("leaving");
    wash.current?.animate([{ clipPath: `circle(${reach}px at ${fx}px ${fy}px)` }, { clipPath: `circle(0px at ${fx}px ${fy}px)` }], { duration: 480, easing: "cubic-bezier(0.65, 0, 0.35, 1)", fill: "forwards" });
    window.setTimeout(props.onClose, 470);
  };

  const send = (what: string) => {
    const t = what.trim();
    if (!t || !ready || pending) return;
    stopSpeaking();
    emoteNow("delight");
    setText(t);
    armHandoff(t, document.querySelector(".ai-field"), document.querySelector(".ai-bot"));
    void routePrompt(t.slice(0, maxChars));
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    send(text || idea);
  };

  // Esc steps back to the hero; spoken words arrive here once written down.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // Esc while listening only stops the mic (voice keys); as rendered, before that handler ran
      if (e.key === "Escape" && !listening) close();
    };
    const onPrompt = (e: Event) => send((e as CustomEvent<string>).detail ?? "");
    window.addEventListener("keydown", onKey);
    window.addEventListener("bara:prompt", onPrompt);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("bara:prompt", onPrompt);
    };
  });

  const state = pending ? "sending" : listening ? "listening" : transcribing || thinking ? "hearing" : text ? "typing" : "idle";
  // Its face answers the reader only, never a build running on some canvas behind the page.
  const mood: Mood =
    conn === "offline" ? "offline" : conn === "connecting" || conn === "reconnecting" ? "connecting" : state === "sending" ? "happy" : state === "idle" ? "idle" : "listening";
  const shown = listening || transcribing ? heard : text;
  const toggleMic = () => {
    if (listening) stopListening();
    else void startListening("auto");
  };

  return createPortal(
    <div className={`agent-intro ph-${phase} st-${state}`} role="dialog" aria-modal="true" aria-label="Tell Bara what to build">
      <div ref={wash} className="ai-wash" />
      {phase === "wash" && (
        <div ref={morph} className="ai-morph" aria-hidden>
          <div ref={morphEyes} className="ai-morph-eyes">
            <i />
            <i />
          </div>
          {/* the label and arrow let go as the button starts to move, instead of blinking out */}
          <div className="ai-morph-rest" style={{ height: from.height }}>
            <span className="cta-label">Start building</span>
            <span className="cta-go">
              <Icon name="send" size={14} />
            </span>
          </div>
        </div>
      )}
      {phase !== "wash" && (
        <div className="ai-bot" style={{ left: cx - size / 2, top: cy - size / 2, width: size, height: size }}>
          <BaraBot size={size} mood={mood} typing={state === "typing" || state === "listening"} typingNonce={keys} emote={emote} />
        </div>
      )}
      <div className="ai-talk" style={{ top: cy + oval.h / 2 + 28 }}>
        <h2 className="ai-ask" aria-live="polite">
          {asked}
          <span className="ai-caret" aria-hidden />
        </h2>
        <form className="ai-field" onSubmit={submit}>
          <button
            type="button"
            className={`ai-mic ${listening ? "on" : ""}`}
            onClick={toggleMic}
            disabled={!ready || pending}
            aria-pressed={listening}
            aria-label={listening ? "Stop listening" : "Talk to Bara"}
            title={listening ? "Send now" : "Talk (or hold Space)"}
          >
            <svg viewBox="0 0 20 20" width="18" height="18" aria-hidden>
              <rect x="7" y="2.5" width="6" height="10" rx="3" />
              <path d="M4.5 9.5a5.5 5.5 0 0 0 11 0M10 15v2.5" />
            </svg>
          </button>
          <input
            ref={input}
            value={shown}
            onChange={(e) => {
              // typing takes over from the mic
              if (listening) cancelListening();
              setText(e.target.value);
              setKeys((k) => k + 1);
            }}
            onKeyDown={(e) => {
              if (e.key === "Tab" && !text && idea && !e.shiftKey) {
                e.preventDefault();
                setText(idea);
              }
            }}
            placeholder={
              listening
                ? voiceMode === "hold"
                  ? "Listening… let go to send"
                  : "Listening… just pause when you're done"
                : transcribing
                  ? "Writing down what you said…"
                  : voiceError
                    ? voiceError
                    : ready
                      ? ghost
                      : "Waking up"
            }
            aria-label="What should Bara build?"
            maxLength={maxChars}
            disabled={!ready || pending || transcribing}
            spellCheck={false}
            autoComplete="off"
          />
          <button type="submit" className="ai-send" disabled={!ready || pending} aria-label={text ? "Build it" : `Build ${idea}`} title={text ? "Build it" : "Build this idea"}>
            {pending ? <span className="spinner light" aria-hidden /> : <Icon name="send" />}
          </button>
        </form>
      </div>
      <button type="button" className="ai-close" onClick={close} aria-label="Back">
        <Icon name="x" />
      </button>
    </div>,
    document.body,
  );
}
