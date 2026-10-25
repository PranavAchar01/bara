import { useEffect, useMemo, useRef, useState } from "react";
import { useApp } from "../state/store";
import { focusKeyOf } from "../three/Viewport3D";
import { setReplies, startListening, stopListening, useVoice } from "../voice/voice";
import { BaraBot, botBubbles } from "../bot/BaraBot";
import { toggleTrace, useTrace } from "../bot/traceState";
import { cancelBuild, routePrompt, startBuild } from "../net/client";
import { addCanvas } from "../state/canvases";
import { Icon } from "../ui/common";

/** A press shorter than this on the docked bot is a tap. */
const HOLD_MS = 220;

/**
 * A new build from the landing's Build dialog: on a fresh canvas when this one already holds a
 * build (that one stays in its tab and in Drafts), and straight onto the Build page.
 */
export function startFreshBuild(prompt: string): void {
  const text = prompt.trim();
  if (!text) return;
  if (useApp.getState().build) addCanvas();
  else useApp.setState({ screen: "workspace" });
  startBuild(text);
}

/** Fills the open prompt (an example chip in the Build dialog) without sending it. */
export function fillPrompt(text: string): void {
  window.dispatchEvent(new CustomEvent("bara:fill", { detail: text }));
}

/** C02 PromptBar: Enter sends build.start; Stop (build.cancel) while running. */
export function PromptBar(props: { docked?: boolean; autoFocus?: boolean; fresh?: boolean; onSent?: () => void; placeholder?: string }) {
  const [text, setText] = useState("");
  const [keys, setKeys] = useState(0);
  const [focused, setFocused] = useState(false);
  const bubbles = useMemo(botBubbles, []);
  const ready = useApp((s) => s.conn === "open" || s.conn === "resyncing");
  const helloSeen = useApp((s) => s.hello !== null);
  const pending = useApp((s) => s.pendingStart !== null);
  const status = useApp((s) => s.build?.status);
  const replaying = useApp((s) => s.replaying);
  // A replay re-performs a finished build; Stop there would cancel nothing real.
  const running = !replaying && (status === "running" || status === "awaiting_input");
  const maxChars = useApp((s) => s.hello?.limits?.max_prompt_chars ?? 2000);
  const disabled = !helloSeen || !ready;
  // The bot is out on the canvas (bot/AgentStage): the docked one steps away, keeping its place.
  const away = useApp((s) => s.agentOut) && !!props.docked;

  const focusKey = useApp((s) => s.focusKey);
  const focusName = useApp((s) => (s.focusKey ? (s.build?.parts.find((p) => focusKeyOf(s.build, p) === s.focusKey)?.card.display_name ?? null) : null));
  const inputRef = useRef<HTMLInputElement>(null);
  const traceOpen = useTrace((s) => s.open) && !!props.docked;
  // The docked bot is two buttons in one: a quick tap opens its thoughts, a hold talks. The mic
  // starts once the press has lasted HOLD_MS, so a tap never flashes the listening state.
  const hold = useRef(0);
  const submit = () => {
    if (disabled || pending || !text.trim()) return;
    // with a part in focus the pill asks about it; it never throws the build away for a new one
    if (props.fresh) startFreshBuild(text.slice(0, maxChars));
    else if (focusKey) window.dispatchEvent(new CustomEvent("bara:ask", { detail: text.trim() }));
    else void routePrompt(text.slice(0, maxChars));
    setText("");
    props.onSent?.();
  };
  const { fresh, onSent } = props;
  useEffect(() => {
    const onFill = (e: Event) => {
      const t = (e as CustomEvent<string>).detail;
      setText(t);
      inputRef.current?.focus();
    };
    window.addEventListener("bara:fill", onFill);
    return () => window.removeEventListener("bara:fill", onFill);
  }, []);
  useEffect(() => {
    const onFocusAsk = () => inputRef.current?.focus();
    window.addEventListener("bara:focus-ask", onFocusAsk);
    return () => window.removeEventListener("bara:focus-ask", onFocusAsk);
  }, []);
  const listening = useVoice((s) => s.listening);
  const heard = useVoice((s) => s.heard);
  const transcribing = useVoice((s) => s.transcribing);
  const caption = useVoice((s) => s.caption);
  const replies = useVoice((s) => s.replies);
  const voiceError = useVoice((s) => s.error);
  const focusOpen = focusKey !== null;
  const sayN = useRef(0);
  const say = useMemo(() => (caption ? { text: caption, n: ++sayN.current } : null), [caption]);
  // Spoken words land here when no part is in focus (the focus card takes them otherwise).
  useEffect(() => {
    const onPrompt = (e: Event) => {
      const t = (e as CustomEvent<string>).detail;
      if (!t || disabled || pending) return;
      if (fresh) startFreshBuild(t.slice(0, maxChars));
      else void routePrompt(t.slice(0, maxChars));
      setText("");
      onSent?.();
    };
    window.addEventListener("bara:prompt", onPrompt);
    return () => window.removeEventListener("bara:prompt", onPrompt);
  }, [disabled, pending, maxChars, fresh, onSent]);

  return (
    <form
      className={`promptbar ${props.docked ? "docked" : ""}`}
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <button
        type="button"
        className={`bot-mic ${listening ? "on" : ""}`}
        onPointerDown={(e) => {
          e.preventDefault();
          if (!props.docked) {
            void startListening();
            return;
          }
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
            toggleTrace();
          } else stopListening();
        }}
        onPointerLeave={() => {
          window.clearTimeout(hold.current);
          hold.current = 0;
          if (listening) stopListening();
        }}
        title={props.docked ? "Tap for my thoughts, hold to talk (or hold Space)" : "Hold to talk (or hold Space)"}
        aria-label={listening ? "Listening, release to send" : "Hold to talk"}
        aria-pressed={listening}
      >
        <BaraBot
          size={props.docked ? 36 : 46}
          typing={(focused && text.length > 0) || traceOpen}
          typingNonce={keys}
          bubbles={bubbles || !!say}
          say={say}
          mood={listening ? "listening" : transcribing ? "thinking" : undefined}
          className={away ? "prompt-bot is-away" : "prompt-bot"}
        />
      </button>
      {listening && (
        <span className="voice-bars" aria-hidden>
          <i />
          <i />
          <i />
          <i />
          <i />
        </span>
      )}
      <input
        ref={inputRef}
        className={`prompt-input ${listening ? "listening" : ""}`}
        value={listening || transcribing ? heard : text}
        readOnly={listening || transcribing}
        maxLength={maxChars}
        autoFocus={props.autoFocus}
        placeholder={
          listening
            ? focusOpen
              ? "Listening… ask about this part"
              : "Listening… describe the device"
            : transcribing
              ? "Writing down what you said…"
              : voiceError
                ? voiceError
                : disabled
                  ? "Waiting for the server"
                  : focusOpen
                    ? `Ask about ${focusName ? `the ${focusName}` : "this part"}, or hold Space to talk`
                    : props.docked
                    ? "Describe another device, or hold Space to talk"
                    : (props.placeholder ?? "Describe the device you want, or hold Space to talk")
        }
        aria-label="Prompt"
        onChange={(e) => {
          setText(e.target.value);
          setKeys((k) => k + 1);
        }}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        disabled={disabled}
      />
      <button
        type="button"
        className={`icon-btn voice-toggle ${replies ? "on" : ""}`}
        onClick={() => setReplies(!replies)}
        title={replies ? "Spoken replies on (V)" : "Spoken replies off (V)"}
        aria-label={replies ? "Turn spoken replies off" : "Turn spoken replies on"}
        aria-pressed={replies}
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
          <path d="M4 10v4h4l5 4V6L8 10H4z" />
          {replies ? <path d="M16.5 8.5a5 5 0 0 1 0 7M19 6a8.5 8.5 0 0 1 0 12" /> : <path d="M17 9l5 6M22 9l-5 6" />}
        </svg>
      </button>
      {running && !text ? (
        <button type="button" className="btn stop" onClick={cancelBuild} title="Stop the build">
          <Icon name="stop" /> Stop
        </button>
      ) : (
        <button type="submit" className="btn primary" disabled={disabled || pending || !text.trim()}>
          {pending ? <span className="spinner light" aria-label="Sending" /> : <Icon name="send" />}
          {focusOpen ? "Ask" : "Build"}
        </button>
      )}
    </form>
  );
}

/** Plain descriptions of a few devices: no product or brand names. */
export const EXAMPLE_PROMPTS = [
  "a handheld arcade device with a joystick",
  "a macropad with a knob",
  "a wireless split keyboard with an OLED",
  "a desk calculator with a screen",
  "a game controller with two thumbsticks",
];

/** C03 ExampleChips: a click starts that build, or (onPick) hands the prompt over instead. */
export function ExampleChips(props: { onPick?: (prompt: string) => void; max?: number }) {
  const helloSeen = useApp((s) => s.hello !== null);
  return (
    <div className="example-chips" aria-label="Examples">
      {EXAMPLE_PROMPTS.slice(0, props.max ?? EXAMPLE_PROMPTS.length).map((p) => (
        <button key={p} type="button" className="example-chip" disabled={!props.onPick && !helloSeen} onClick={() => (props.onPick ? props.onPick(p) : startBuild(p))}>
          {p}
        </button>
      ))}
    </div>
  );
}
