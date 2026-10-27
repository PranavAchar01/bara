import { useEffect, useMemo, useRef, useState } from "react";
import { useApp } from "../state/store";
import { focusKeyOf } from "../three/Viewport3D";
import { setReplies, startListening, stopListening, useVoice } from "../voice/voice";
import { BaraBot, botBubbles } from "../bot/BaraBot";
import { toggleTrace, useTrace } from "../bot/traceState";
import { cancelBuild, startBuild } from "../net/client";
import { addCanvas } from "../state/canvases";
import { act } from "../bot/act";
import { Icon } from "../ui/common";
import { VoiceKey } from "./VoiceKey";
import { vlabel } from "../ui/format";
import { STAGE_IDS } from "../spec/types";

/** The part a part.added event names, or null. */
function partName(raw: string): string | null {
  try {
    const p = (JSON.parse(raw) as { payload?: { part?: { label?: string; card?: { display_name?: string } } } }).payload?.part;
    return p?.label ?? p?.card?.display_name ?? null;
  } catch {
    return null;
  }
}

/** Where the build is, in a few words: the part it just placed, else the stage it is in. */
function useWhere(): string | null {
  return useApp((s) => {
    const st = s.build?.status;
    if (st !== "running" && st !== "awaiting_input") return null;
    if (st === "awaiting_input") return "Waiting for you";
    const id = STAGE_IDS.find((k) => s.view.stages[k]?.status === "active");
    const stage = id ? (s.view.stages[id]?.label ?? vlabel(s.vocab, "stages", id)) : null;
    const bid = s.build?.build_id;
    for (let i = s.log.length - 1, n = 0; i >= 0 && n < 40; i--, n++) {
      const e = s.log[i];
      if (e.dir !== "in" || (e.buildId && e.buildId !== bid)) continue;
      if (e.type === "stage.started") break;
      if (e.type === "part.added") return partName(e.raw) ?? stage;
    }
    return stage ?? "Working";
  });
}

/** Small thinking dots pinned at the right end of the field, with the part or stage Bara is on. */
function WorkingDots() {
  const where = useWhere();
  if (!where) return null;
  return (
    <span className="prompt-working" role="status" aria-live="polite" title={where}>
      <span className="pw-dots" aria-hidden>
        <i />
        <i />
        <i />
      </span>
      <span className="pw-where">{where}</span>
    </span>
  );
}

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
  const done = useApp((s) => s.build?.status === "done");
  const focusName = useApp((s) => (s.focusKey ? (s.build?.parts.find((p) => focusKeyOf(s.build, p) === s.focusKey)?.card.display_name ?? null) : null));
  const inputRef = useRef<HTMLInputElement>(null);
  const traceOpen = useTrace((s) => s.open) && !!props.docked;
  // The docked bot is two buttons in one: a quick tap opens its thoughts, a hold talks. The mic
  // starts once the press has lasted HOLD_MS, so a tap never flashes the listening state.
  const hold = useRef(0);
  const submit = () => {
    if (disabled || pending || !text.trim()) return;
    // one prompt for everything: a change, a question, another device or a new one (bot/act.ts);
    // from the landing's Build dialog it is always a new build
    if (props.fresh) startFreshBuild(text.slice(0, maxChars));
    else void act(text.slice(0, maxChars));
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
    // a start written for you (the selection pill's Build around it): the cursor waits at its end
    const onPrefill = (e: Event) => {
      const t = (e as CustomEvent<string>).detail ?? "";
      setText(t);
      requestAnimationFrame(() => {
        const el = inputRef.current;
        if (!el) return;
        el.focus();
        el.setSelectionRange(t.length, t.length);
      });
    };
    window.addEventListener("bara:focus-ask", onFocusAsk);
    window.addEventListener("bara:prefill", onPrefill);
    return () => {
      window.removeEventListener("bara:focus-ask", onFocusAsk);
      window.removeEventListener("bara:prefill", onPrefill);
    };
  }, []);
  const listening = useVoice((s) => s.listening);
  const heard = useVoice((s) => s.heard);
  const transcribing = useVoice((s) => s.transcribing);
  const caption = useVoice((s) => s.caption);
  const replies = useVoice((s) => s.replies);
  const voiceError = useVoice((s) => s.error);
  const voiceMode = useVoice((s) => s.mode);
  const sendHint = voiceMode === "hold" ? "let go to send" : "pause to send";
  const focusOpen = focusKey !== null;
  const sayN = useRef(0);
  const say = useMemo(() => (caption ? { text: caption, n: ++sayN.current } : null), [caption]);
  // Spoken words land here when no part is in focus (the focus card takes them otherwise).
  useEffect(() => {
    const onPrompt = (e: Event) => {
      const t = (e as CustomEvent<string>).detail;
      if (!t || disabled || pending) return;
      if (fresh) startFreshBuild(t.slice(0, maxChars));
      else void act(t.slice(0, maxChars));
      setText("");
      onSent?.();
    };
    // spoken lines arrive on either event (a part in focus or not); both go the same way
    window.addEventListener("bara:prompt", onPrompt);
    window.addEventListener("bara:ask", onPrompt);
    return () => {
      window.removeEventListener("bara:prompt", onPrompt);
      window.removeEventListener("bara:ask", onPrompt);
    };
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
            void startListening("hold");
            return;
          }
          window.clearTimeout(hold.current);
          hold.current = window.setTimeout(() => {
            hold.current = 0;
            void startListening("hold");
          }, HOLD_MS);
        }}
        onPointerUp={() => {
          if (hold.current) {
            window.clearTimeout(hold.current);
            hold.current = 0;
            toggleTrace();
          } else stopListening();
        }}
        onPointerCancel={() => {
          // a touch taken over by the browser (a scroll, a system gesture) never sends pointerup
          window.clearTimeout(hold.current);
          hold.current = 0;
          if (listening) stopListening();
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
          quiet={props.docked}
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
      <span className="prompt-field">
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
              ? `Listening… ask about this part, ${sendHint}`
              : `Listening… describe the device, ${sendHint}`
            : transcribing
              ? "Writing down what you said…"
              : voiceError
                ? voiceError
                : disabled
                  ? "Waiting for the server"
                  : focusOpen
                    ? `Change or ask about ${focusName ? `the ${focusName}` : "this part"}`
                    : props.docked && done
                    ? "Change it, or describe something new"
                    : props.docked && running
                    ? "Describe another device"
                    : props.docked
                    ? "Describe a device, or hold Space"
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
      {props.docked && !text && !listening && !transcribing && <WorkingDots />}
      </span>
      {/* the way in to talking, for anyone who hasn't found Space yet: tap it (or Space) to talk
          hands-free, hold Space to talk while held. The ring grows with the voice. */}
      <button
        type="button"
        className={`talk-key ${listening ? "on" : ""}`}
        // keep focus where it was, so a later Space press talks instead of pressing this button again
        onPointerDown={(e) => e.preventDefault()}
        onClick={() => (listening ? stopListening() : void startListening("auto"))}
        disabled={disabled}
        title={listening ? "Send now (Space)" : "Talk: tap Space and speak, or hold Space while you talk"}
        aria-label={listening ? "Send what you said" : "Talk to Bara"}
        aria-pressed={listening}
      >
        <svg viewBox="0 0 20 20" width="14" height="14" aria-hidden>
          <rect x="7" y="2.5" width="6" height="10" rx="3" />
          <path d="M4.5 9.5a5.5 5.5 0 0 0 11 0M10 15v2.5" />
        </svg>
        <kbd>Space</kbd>
      </button>
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
      <VoiceKey />
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
