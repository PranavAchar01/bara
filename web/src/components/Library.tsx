// Your builds, at the bottom of Home (Figma 21): every build made in this browser, newest first,
// with its canvas snapshot. Click to reopen; × (twice) to remove; type to filter.
import { useEffect, useMemo, useState } from "react";
import { openLibraryBuild, openSaved } from "../net/client";
import { showToast } from "../state/store";
import { deleteEntry, loadEntry, useLibrary, type LibraryCard } from "../library/library";

const DAY = 86_400_000;

function when(t: number, now: number): string {
  const d = now - t;
  if (d < 60_000) return "just now";
  if (d < 3_600_000) return `${Math.round(d / 60_000)} min ago`;
  const date = new Date(t);
  const today = new Date(now);
  if (date.toDateString() === today.toDateString()) return date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  if (d < 2 * DAY && new Date(now - DAY).toDateString() === date.toDateString()) return "Yesterday";
  return date.toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" });
}

const STATUS_LABEL: Record<string, string> = {
  running: "In progress",
  awaiting_input: "Needs an answer",
  failed: "Failed",
  cancelled: "Stopped",
};

function BuildCard(props: { card: LibraryCard; now: number }) {
  const { card } = props;
  const [confirm, setConfirm] = useState(false);
  const [opening, setOpening] = useState(false);
  const open = async () => {
    setOpening(true);
    const entry = await loadEntry(card.build_id).catch(() => null);
    if (!entry && card.remote) {
      // not saved in this browser: replay the engine's stored events
      await openLibraryBuild(card.build_id);
      setOpening(false);
      return;
    }
    setOpening(false);
    if (!entry) {
      showToast("That build couldn't be read from this browser's storage.");
      return;
    }
    openSaved(entry);
  };
  const status = STATUS_LABEL[card.status];
  return (
    <li className={`lib-card ${opening ? "opening" : ""}`}>
      <button type="button" className="lib-open" onClick={() => void open()} aria-label={`Open “${card.prompt}”`}>
        <span className="lib-thumb">
          {card.thumb ? <img src={card.thumb} alt="" loading="lazy" /> : <span className="lib-nothumb">No preview yet</span>}
        </span>
        <span className="lib-meta">
          <span className="lib-title">{card.prompt}</span>
          <span className="lib-sub">
            <span className="lib-line">
              {card.summary ? `${card.summary} · ` : ""}
              {when(card.updatedAt, props.now)}
            </span>
            {card.mock && <span className="lib-pill">Demo</span>}
            {status && <span className={`lib-pill st-${card.status}`}>{status}</span>}
          </span>
        </span>
      </button>
      <button
        type="button"
        className={`lib-del ${confirm ? "confirm" : ""}`}
        onClick={() => {
          if (confirm) void deleteEntry(card.build_id);
          else setConfirm(true);
        }}
        onBlur={() => setConfirm(false)}
        aria-label={confirm ? `Remove “${card.prompt}” for good` : `Remove “${card.prompt}”`}
        title={confirm ? (card.remote ? "Click again to delete it for everyone" : "Click again to remove it") : "Remove from the library"}
      >
        {confirm ? "Remove?" : "×"}
      </button>
    </li>
  );
}

export function Library() {
  const cards = useLibrary((s) => s.cards);
  const ready = useLibrary((s) => s.ready);
  const unavailable = useLibrary((s) => s.unavailable);
  const [q, setQ] = useState("");
  // "2 min ago" is worked out when the list changes, which is when Home is looked at
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => setNow(Date.now()), [cards]);
  const shown = useMemo(() => {
    const t = q.trim().toLowerCase();
    return t ? cards.filter((c) => `${c.prompt} ${c.summary}`.toLowerCase().includes(t)) : cards;
  }, [cards, q]);
  if (!ready) return null;
  return (
    <section className="library" aria-labelledby="lib-h">
      <header className="lib-head">
        <div>
          <span className="lib-kicker">Your builds · {cards.length}</span>
          <h2 id="lib-h">{cards.length ? "Pick up where you left off" : "Your builds will live here"}</h2>
        </div>
        {cards.length > 3 && (
          <input className="lib-search" type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search your builds" aria-label="Search your builds" />
        )}
      </header>
      {cards.length === 0 ? (
        <p className="lib-empty">
          {unavailable
            ? "This browser isn't keeping storage (a private window?), so builds can't be saved here."
            : "Every device you build is saved here with a picture of it, so you can come back to it later."}
        </p>
      ) : shown.length === 0 ? (
        <p className="lib-empty">No build matches “{q}”.</p>
      ) : (
        <ul className="lib-grid">
          {shown.map((c) => (
            <BuildCard key={c.build_id} card={c} now={now} />
          ))}
        </ul>
      )}
      {cards.length > 0 && <p className="lib-note">Finished builds are kept on the engine, so everyone who opens this site sees them; deleting one removes it for everyone. A build opens right away; changing it works while the engine still has it.</p>}
    </section>
  );
}
