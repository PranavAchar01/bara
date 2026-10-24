import { useEffect, useMemo, useRef, useState } from "react";
import { useApp } from "../state/store";
import { focusKeyOf } from "../three/Viewport3D";
import { setReplies, startListening, stopListening, useVoice } from "../voice/voice";
import { BaraBot, botBubbles } from "../bot/BaraBot";
import { cancelBuild, routePrompt, startBuild } from "../net/client";
import { demoPrompts } from "../spec/fixtures";
import { Icon } from "../ui/common";

/** C02 PromptBar: Enter sends build.start; Stop (build.cancel) while running. */
export function PromptBar(props: { docked?: boolean; autoFocus?: boolean }) {
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
  const submit = () => {
    if (disabled || pending || !text.trim()) return;
    // with a part in focus the pill asks about it; it never throws the build away for a new one
    if (focusKey) window.dispatchEvent(new CustomEvent("bara:ask", { detail: text.trim() }));
    else void routePrompt(text.slice(0, maxChars));
    setText("");
  };
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
      setText(t);
      void routePrompt(t.slice(0, maxChars));
      setText("");
    };
    window.addEventListener("bara:prompt", onPrompt);
    return () => window.removeEventListener("bara:prompt", onPrompt);
  }, [disabled, pending, maxChars]);

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
          void startListening();
        }}
        onPointerUp={() => stopListening()}
        onPointerLeave={() => listening && stopListening()}
        title="Hold to talk (or hold Space)"
        aria-label={listening ? "Listening, release to send" : "Hold to talk"}
        aria-pressed={listening}
      >
        <BaraBot
          size={props.docked ? 36 : 46}
          typing={focused && text.length > 0}
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
                    : "Describe the device you want, or hold Space to talk"
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

/** C03 ExampleChips: one chip per demo prompt from the stream fixtures. */
export function ExampleChips() {
  const [items, setItems] = useState<{ fixture: string; prompt: string }[]>([]);
  const helloSeen = useApp((s) => s.hello !== null);
  useEffect(() => {
    let live = true;
    void demoPrompts().then((p) => {
      if (live) setItems(p);
    });
    return () => {
      live = false;
    };
  }, []);
  return (
    <div className="example-chips" aria-label="Examples">
      {items.map((it) => (
        <button key={it.fixture} type="button" className="example-chip" disabled={!helloSeen} onClick={() => startBuild(it.prompt)}>
          {it.prompt}
        </button>
      ))}
    </div>
  );
}
