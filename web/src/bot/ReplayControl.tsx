// Replay button for a finished build: Replay / Stop, a speed picker, a thin progress bar.
// "R" toggles it when focus is not in a text field.
import { useEffect } from "react";
import { useApp } from "../state/store";
import { Icon } from "../ui/common";
import { SPEEDS, canReplay, setReplaySpeed, startReplay, stopReplay, toggleReplay, useReplay } from "./replay";
import "./replay.css";

function PlayIcon() {
  return (
    <svg width={14} height={14} viewBox="0 0 16 16" aria-hidden>
      <path d="M5 3.5v9l7-4.5z" fill="currentColor" />
    </svg>
  );
}

function speedLabel(s: number): string {
  return s === 0.5 ? "½×" : `${s}×`;
}

export function ReplayControl() {
  const build = useApp((s) => s.build);
  const replaying = useApp((s) => s.replaying);
  const speed = useReplay((s) => s.speed);
  const progress = useReplay((s) => s.progress);
  const loading = useReplay((s) => s.loading);
  const visible = replaying || canReplay(build);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey || e.repeat) return;
      if (e.key !== "r" && e.key !== "R") return;
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable)) return;
      const s = useApp.getState();
      if (!s.replaying && (s.screen !== "workspace" || !canReplay(s.build))) return;
      e.preventDefault();
      toggleReplay();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  if (!visible) return null;
  return (
    <div className={`replay ${replaying ? "is-playing" : ""}`}>
      {replaying ? (
        <button type="button" className="btn sm replay-btn" onClick={stopReplay} title="Stop the replay (R)">
          <Icon name="stop" size={12} /> Stop
        </button>
      ) : (
        <button
          type="button"
          className="btn sm replay-btn"
          onClick={() => void startReplay(speed)}
          disabled={loading}
          title="Watch the bot build it again (R)"
        >
          <PlayIcon /> {loading ? "Loading" : "Replay"}
        </button>
      )}
      <div className="replay-speed" role="radiogroup" aria-label="Replay speed">
        {SPEEDS.map((s) => (
          <button
            key={s}
            type="button"
            role="radio"
            aria-checked={speed === s}
            className={speed === s ? "active" : undefined}
            disabled={replaying}
            onClick={() => setReplaySpeed(s)}
            title={`${s}× speed`}
          >
            {speedLabel(s)}
          </button>
        ))}
      </div>
      {replaying && (
        <div
          className="replay-progress"
          role="progressbar"
          aria-label="Replay progress"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(progress * 100)}
        >
          <span style={{ transform: `scaleX(${progress})` }} />
        </div>
      )}
    </div>
  );
}
