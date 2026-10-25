import { useEffect, useRef, useState } from "react";
import { recheckEngineVoice } from "../voice/voice";
import { saveKey, useVoiceKey } from "../voice/voiceKey";
import "../styles/voicekey.css";

/** A small calm note and field for the visitor's own OpenAI key. Voice models are the one part
 *  Bara does not front; text and the rest of the build stay free. The key stays in this browser. */
export function VoiceKey() {
  const hasKey = useVoiceKey((s) => s.hasKey);
  const needsKey = useVoiceKey((s) => s.needsKey);
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const away = (e: PointerEvent) => {
      if (root.current && !root.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", away);
    return () => document.removeEventListener("pointerdown", away);
  }, [open]);

  const apply = async (key: string) => {
    setBusy(true);
    await saveKey(key);
    recheckEngineVoice();
    setBusy(false);
    setValue("");
    setOpen(false);
  };

  return (
    <div className="voicekey" ref={root}>
      <button
        type="button"
        className={`icon-btn voicekey-btn ${hasKey ? "on" : ""} ${needsKey ? "needs" : ""}`}
        onClick={() => setOpen(!open)}
        title="Voice settings"
        aria-label="Voice settings"
        aria-expanded={open}
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
          <circle cx="8" cy="15" r="4" />
          <path d="M11 12l8-8M16 7l2.5 2.5M14 9l2 2" />
        </svg>
      </button>
      {open && (
        <form
          className="voicekey-pop"
          onSubmit={(e) => {
            e.preventDefault();
            if (value.trim()) void apply(value);
          }}
        >
          <p className="voicekey-title">Voice uses your own OpenAI key</p>
          <p className="voicekey-note">
            Kept only in this browser. Text and the rest of the build are free; only the voice models need your key.
          </p>
          <input
            type="password"
            autoComplete="off"
            spellCheck={false}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder={hasKey ? "A key is saved" : "sk-..."}
            aria-label="OpenAI API key for voice"
          />
          <div className="voicekey-row">
            <button type="submit" className="btn primary" disabled={busy || !value.trim()}>
              Save
            </button>
            {hasKey && (
              <button type="button" className="btn" disabled={busy} onClick={() => void apply("")}>
                Remove
              </button>
            )}
          </div>
        </form>
      )}
    </div>
  );
}
