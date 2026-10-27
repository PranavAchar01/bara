// The popups above the prompt: Bara's line about what just happened, gone after a moment. Lines come
// from the build stream (mood.speechFor, the same words the voice says), the agent's beats and spoken replies.
import { useEffect } from "react";
import { useApp } from "../state/store";
import { useVoice } from "../voice/voice";
import { speechFor } from "./mood";
import { popup, usePopups } from "./popups";

/** One stream line this often, these always (mirrors the voice). */
const GAP_MS = 2500;
const ALWAYS = new Set(["build.done", "build.failed", "clarify.request"]);

export function BotPopups() {
  const items = usePopups((s) => s.items);
  useEffect(() => {
    let seen = useApp.getState().log.at(-1)?.id ?? 0;
    let lastAt = 0;
    const offLog = useApp.subscribe((s) => {
      const lastId = s.log.at(-1)?.id ?? seen;
      if (lastId === seen) return;
      const fresh = s.log.filter((e) => e.id > seen && e.dir === "in" && (!e.buildId || e.buildId === s.build?.build_id));
      seen = lastId;
      for (const e of fresh) {
        const line = speechFor(e);
        const now = performance.now();
        if (!line || (!ALWAYS.has(e.type) && now - lastAt < GAP_MS)) continue;
        lastAt = now;
        popup(line);
      }
    });
    // a spoken reply (an answer, an explanation) shows as a popup while it is said
    const offVoice = useVoice.subscribe((v, prev) => {
      if (v.caption && v.caption !== prev.caption) popup(v.caption);
    });
    return () => {
      offLog();
      offVoice();
    };
  }, []);
  if (!items.length) return null;
  return (
    <div className="bot-popups" aria-live="polite">
      {items.map((p) => (
        <div key={p.id} className="bot-popup" role="status">
          {p.text}
        </div>
      ))}
    </div>
  );
}
