// The landing's only control: Bara and its speech bubble. The bubble is the prompt. Start typing
// anywhere and the words land in it; hold the bot (or Space) to say it instead. While it is empty
// the bubble types out ideas, and Tab or the arrow builds the one showing. The bot stays put:
// all its life is in its face, so nothing on the page moves out from under the reader.
import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { BaraBot } from "../bot/BaraBot";
import { reducedMotion } from "../bot/spring";
import type { Emote, Mood } from "../bot/mood";
import { routePrompt } from "../net/client";
import { demoPrompts } from "../spec/fixtures";
import { useApp } from "../state/store";
import { Icon } from "../ui/common";
import { startListening, stopListening, useVoice } from "../voice/voice";

/** A press shorter than this is a tap (open the bubble); a longer one talks. */
const HOLD_MS = 220;
const IDEAS = ["a macropad with one big knob", "a wireless split keyboard with an OLED", "a 60% keyboard with Choc switches", "something cool for my desk"];
const TYPE_MS = 45;
const SHOW_MS = 2400;

/** The idea being typed out in the empty bubble, letter by letter, then rubbed out for the next. */
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

export function HeroAgent() {
  const [text, setText] = useState("");
  const [focused, setFocused] = useState(false);
  const [keys, setKeys] = useState(0);
  const [emote, setEmote] = useState<{ kind: Emote; n: number } | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const hold = useRef(0);
  const ready = useApp((s) => s.hello !== null && (s.conn === "open" || s.conn === "resyncing"));
  const pending = useApp((s) => s.pendingStart !== null);
  const maxChars = useApp((s) => s.hello?.limits?.max_prompt_chars ?? 2000);
  const listening = useVoice((s) => s.listening);
  const heard = useVoice((s) => s.heard);
  const transcribing = useVoice((s) => s.transcribing);
  const { ghost, idea } = useIdeaGhost(!text && !listening && !transcribing && !pending);
  const conn = useApp((s) => s.conn);
  const size = useMemo(() => (window.innerWidth < 600 ? 96 : 150), []);

  const send = (what: string) => {
    const t = what.trim();
    if (!t || !ready || pending) return;
    setEmote((e) => ({ kind: "delight", n: (e?.n ?? 0) + 1 }));
    setText(t);
    void routePrompt(t.slice(0, maxChars));
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    send(text || idea);
  };

  // Typing anywhere on the page goes into the bubble. Space is left alone: holding it talks.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey || e.key.length !== 1 || e.key === " ") return;
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable)) return;
      // the voice keys (V) would otherwise read this letter as a shortcut
      e.stopPropagation();
      input.current?.focus();
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, []);

  // Spoken words arrive here once written down.
  useEffect(() => {
    const onPrompt = (e: Event) => send((e as CustomEvent<string>).detail ?? "");
    window.addEventListener("bara:prompt", onPrompt);
    return () => window.removeEventListener("bara:prompt", onPrompt);
  });

  const state = pending ? "sending" : listening ? "listening" : transcribing ? "hearing" : focused || text ? "typing" : "idle";
  // Its face answers the reader only, never a build running on some canvas behind the page.
  const mood: Mood =
    conn === "offline" ? "offline" : conn === "connecting" || conn === "reconnecting" ? "connecting" : state === "sending" ? "happy" : state === "idle" ? "idle" : "listening";
  const shown = listening ? heard : transcribing ? heard || "" : text;

  return (
    <div className={`hero-agent st-${state}`}>
      <button
        type="button"
        className="hero-bot"
        aria-label="Bara. Tap to type, hold to talk."
        title="Tap to type, hold to talk"
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
            input.current?.focus();
          } else stopListening();
        }}
        onPointerLeave={() => {
          if (hold.current) {
            window.clearTimeout(hold.current);
            hold.current = 0;
          } else if (listening) stopListening();
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            input.current?.focus();
          }
        }}
      >
        <span className="hero-bot-float">
          <BaraBot size={size} mood={mood} typing={state === "typing" || state === "listening"} typingNonce={keys} emote={emote} />
        </span>
      </button>
      <form className="hero-bubble" onSubmit={submit}>
        {state === "listening" && <span className="hero-mic" aria-hidden />}
        <input
          ref={input}
          value={shown}
          onChange={(e) => {
            setText(e.target.value);
            setKeys((k) => k + 1);
          }}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          onKeyDown={(e) => {
            if (e.key === "Tab" && !text && idea && !e.shiftKey) {
              e.preventDefault();
              setText(idea);
            }
          }}
          placeholder={state === "listening" ? "Listening" : ready ? ghost : "Waking up"}
          aria-label="Tell Bara what to build"
          maxLength={maxChars}
          disabled={!ready || pending || listening || transcribing}
          spellCheck={false}
          autoComplete="off"
        />
        <button type="submit" className="hero-send" disabled={!ready || pending} aria-label={text ? "Build it" : `Build ${idea}`} title={text ? "Build it" : "Build this idea"}>
          {pending ? <span className="spinner light" aria-hidden /> : <Icon name="send" />}
        </button>
      </form>
    </div>
  );
}
