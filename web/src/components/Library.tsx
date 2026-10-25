// The Library page (/library): finished builds from the engine (the gallery, one per kind of device,
// every check held) with its own Build button, then this browser's drafts in Bara's own language: a small
// Bara keeps the shelf, the newest draft sits large on a gridded plate like the hero's, and the rest stand
// on a shelf by day. Every tile shows the build's finished product alone, rendered (library/shots.ts,
// scripts/render-shots.mjs); one not rendered yet falls back to a drawing of its parts or, for a draft, a
// blueprint drawn from what was asked for. Click to reopen; × (twice) to delete a build, which only hides it
// (Deleted, at the foot of the page, brings it back); type to filter. Tiles rise in once on load and then
// hold still: only the hovered card moves.
import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { openLibraryBuild, openSaved } from "../net/client";
import { showToast, useApp } from "../state/store";
import { Icon } from "../ui/common";
import { deleteEntry, loadEntry, restoreEntry, useLibrary, type LibraryCard } from "../library/library";
import { loadGallery, reloadGallery, useGallery, type GalleryItem } from "../library/gallery";
import { BuildStill } from "./BuildScene";
import { openBuildDialog } from "./BuildDialog";
import { OpenSource } from "./OpenSource";
import "../styles/library.css";

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

/** The shelf a build stands on: today, yesterday, this week, or earlier. */
function shelfOf(t: number, now: number): string {
  const date = new Date(t).toDateString();
  if (date === new Date(now).toDateString()) return "Today";
  if (date === new Date(now - DAY).toDateString()) return "Yesterday";
  if (now - t < 7 * DAY) return "This week";
  return "Earlier";
}

const STATUS_LABEL: Record<string, string> = {
  running: "In progress",
  awaiting_input: "Needs an answer",
  failed: "Failed",
  cancelled: "Stopped",
};

async function openCard(card: LibraryCard): Promise<void> {
  const entry = await loadEntry(card.build_id).catch(() => null);
  if (!entry && card.remote) {
    // not saved in this browser: replay the engine's stored events
    await openLibraryBuild(card.build_id);
    return;
  }
  if (!entry) {
    showToast("That build couldn't be read from this browser's storage.");
    return;
  }
  openSaved(entry);
}

/** A blueprint for a build with no picture: keys, a knob, a screen or two halves, read off the request. */
function Blueprint(props: { prompt: string }) {
  const p = props.prompt.toLowerCase();
  const grid = /(\d+)\s*[x×]\s*(\d+)/.exec(p);
  const keyCount = /(\d+)\s*(?:-|\s)?keys?\b/.exec(p);
  const split = /split/.test(p);
  const knob = /knob|encoder|dial/.test(p);
  const screen = /oled|screen|display/.test(p);
  let rows = 4;
  let cols = 12;
  if (grid) {
    cols = Math.min(8, Number(grid[1]));
    rows = Math.min(6, Number(grid[2]));
    if (rows > cols) [rows, cols] = [cols, rows];
  } else if (/macropad/.test(p)) {
    const n = keyCount ? Number(keyCount[1]) : 9;
    cols = n <= 4 ? n : Math.ceil(Math.sqrt(n));
    rows = Math.ceil(n / cols);
  } else if (/60%|sixty/.test(p)) {
    rows = 5;
    cols = 14;
  } else if (split) {
    rows = 3;
    cols = 12;
  } else if (!/keyboard|keys|pad/.test(p)) {
    rows = 2;
    cols = 3;
  }
  const u = 10;
  const gap = split ? 2.2 * u : 0;
  const extra = (knob ? 1.6 * u : 0) + (screen ? 2.6 * u : 0);
  const w = cols * u + gap + extra + 2 * u;
  const h = Math.max(rows * u, screen ? 2 * u : 0) + 2 * u;
  const keys = [];
  for (let r = 0; r < rows; r++)
    for (let c = 0; c < cols; c++) {
      const x = u + c * u + (split && c >= cols / 2 ? gap : 0);
      keys.push(<rect key={`${r}-${c}`} x={x + 1.2} y={u + r * u + 1.2} width={u - 2.4} height={u - 2.4} rx={1.6} />);
    }
  const right = u + cols * u + gap;
  return (
    <svg className="lib-blueprint" viewBox={`${-u} ${-u} ${w + 2 * u} ${h + 2 * u}`} preserveAspectRatio="xMidYMid meet" aria-hidden>
      {split ? (
        <>
          <rect className="bp-case" x={u * 0.4} y={u * 0.4} width={(cols / 2) * u + u * 1.2} height={rows * u + u * 1.2} rx={3} />
          <rect className="bp-case" x={u * 0.4 + (cols / 2) * u + gap} y={u * 0.4} width={(cols / 2) * u + u * 1.2 + extra} height={rows * u + u * 1.2} rx={3} />
        </>
      ) : (
        <rect className="bp-case" x={u * 0.4} y={u * 0.4} width={w - u * 0.8} height={h - u * 0.8} rx={4} />
      )}
      <g className="bp-keys">{keys}</g>
      {knob && <circle className="bp-part" cx={right + 0.8 * u} cy={u * 1.6} r={u * 0.62} />}
      {screen && <rect className="bp-part" x={right + (knob ? 1.6 * u : 0) + u * 0.2} y={u * 1.1} width={u * 2.2} height={u * 1.1} rx={1.2} />}
      <text className="bp-dim" x={u * 0.4} y={-u * 0.25}>
        {rows}×{cols}
      </text>
    </svg>
  );
}

/** The picture of a build: the rendered product alone (scripts/render-shots.mjs), or a blueprint drawn from the
 *  request until it has one. Never the workspace snapshot: that one stands on the studio floor and grid. */
function Picture(props: { card: LibraryCard }) {
  const [broken, setBroken] = useState(false);
  if (props.card.shot && !broken) return <img className="lib-shot" src={props.card.shot} alt="" loading="lazy" decoding="async" onError={() => setBroken(true)} />;
  return <Blueprint prompt={props.card.prompt} />;
}

/** Leans a card a few degrees toward the pointer. */
function tilt(e: ReactPointerEvent<HTMLElement>) {
  const el = e.currentTarget;
  const r = el.getBoundingClientRect();
  el.style.setProperty("--tilt-x", `${(((e.clientY - r.top) / r.height - 0.5) * -5).toFixed(2)}deg`);
  el.style.setProperty("--tilt-y", `${(((e.clientX - r.left) / r.width - 0.5) * 6).toFixed(2)}deg`);
}
function untilt(e: ReactPointerEvent<HTMLElement>) {
  e.currentTarget.style.setProperty("--tilt-x", "0deg");
  e.currentTarget.style.setProperty("--tilt-y", "0deg");
}

/** Deletes a build from the library, in two clicks. Soft: the build is hidden, never erased, and Deleted
 *  at the foot of the page restores it. */
function Remove(props: { id: string; name: string; after?: () => void }) {
  const [confirm, setConfirm] = useState(false);
  return (
    <button
      type="button"
      className={`lib-del ${confirm ? "confirm" : ""}`}
      onClick={() => {
        if (confirm) void deleteEntry(props.id).then(props.after);
        else setConfirm(true);
      }}
      onBlur={() => setConfirm(false)}
      aria-label={confirm ? `Delete “${props.name}”, it can be restored` : `Delete “${props.name}”`}
      title={confirm ? "Click again to delete. It stays restorable under Deleted." : "Delete from the library"}
    >
      {confirm ? "Delete?" : <Icon name="x" size={12} />}
    </button>
  );
}

/** The deleted builds, folded away at the foot of the page, each one a click from coming back. */
function Deleted() {
  const hidden = useLibrary((s) => s.hidden);
  const [open, setOpen] = useState(false);
  if (hidden.length === 0) return null;
  return (
    <section className="lib-deleted" aria-label="Deleted builds">
      <button type="button" className="lib-deleted-toggle mono" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        Deleted <span>{hidden.length}</span>
      </button>
      {open && (
        <ul className="lib-deleted-list">
          {hidden.map((c) => (
            <li key={c.build_id}>
              <span>{c.summary || c.prompt}</span>
              <button
                type="button"
                className="btn sm"
                onClick={() =>
                  void restoreEntry(c.build_id).then(() => {
                    void reloadGallery();
                  })
                }
              >
                Restore
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Meta(props: { card: LibraryCard; now: number }) {
  const { card } = props;
  const device = card.summary.split(" · ")[0];
  return (
    <span className="lib-meta mono">
      {device && <span>{device}</span>}
      {card.parts > 0 && <span>{card.parts} parts</span>}
      <span>{when(card.updatedAt, props.now)}</span>
    </span>
  );
}

function BuildCard(props: { card: LibraryCard; now: number; index: number }) {
  const { card } = props;
  const [opening, setOpening] = useState(false);
  const status = STATUS_LABEL[card.status];
  const open = async () => {
    setOpening(true);
    await openCard(card);
    setOpening(false);
  };
  return (
    <li className={`lib-card ${opening ? "opening" : ""}`} style={{ animationDelay: `${Math.min(props.index, 12) * 40}ms` }} onPointerMove={tilt} onPointerLeave={untilt}>
      <button type="button" className="lib-open" onClick={() => void open()} aria-label={`Open “${card.prompt}”`}>
        <span className="lib-pic">
          <Picture card={card} />
          {status && <span className={`lib-badge st-${card.status}`}>{status}</span>}
          {card.mock && <span className="lib-badge">Demo</span>}
          <span className="lib-go" aria-hidden>
            Open <Icon name="send" size={12} />
          </span>
        </span>
        <span className="lib-title">{card.prompt}</span>
        <Meta card={card} now={props.now} />
      </button>
      <Remove id={card.build_id} name={card.prompt} after={reloadGallery} />
    </li>
  );
}

/** The newest build, large: the one you most likely came back for. */
function Latest(props: { card: LibraryCard; now: number }) {
  const { card } = props;
  const [opening, setOpening] = useState(false);
  const open = async () => {
    setOpening(true);
    await openCard(card);
    setOpening(false);
  };
  return (
    <article className={`lib-latest ${opening ? "opening" : ""}`} onPointerMove={tilt} onPointerLeave={untilt}>
      <button type="button" className="lib-latest-pic" onClick={() => void open()} aria-label={`Open “${card.prompt}”`}>
        <Picture card={card} />
      </button>
      <div className="lib-latest-copy">
        <span className="lib-kicker mono">Latest · {when(card.updatedAt, props.now)}</span>
        <h3>{card.prompt}</h3>
        <Meta card={card} now={props.now} />
        <button type="button" className="lib-pickup" onClick={() => void open()} disabled={opening}>
          {opening ? <span className="spinner light" aria-hidden /> : null}
          Pick it up
          <span className="cta-go" aria-hidden>
            <Icon name="send" size={14} />
          </span>
        </button>
      </div>
      <Remove id={card.build_id} name={card.prompt} after={reloadGallery} />
    </article>
  );
}

/** A small Bara keeping the shelf; its eyes follow the pointer like the Build button's. */
function Keeper() {
  const eyes = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    const move = (e: PointerEvent) => {
      const el = eyes.current;
      if (!el) return;
      const r = el.getBoundingClientRect();
      const dx = e.clientX - (r.left + r.width / 2);
      const dy = e.clientY - (r.top + r.height / 2);
      const d = Math.hypot(dx, dy) || 1;
      const k = Math.min(1, d / 240);
      el.style.setProperty("--look-x", `${((dx / d) * 2 * k).toFixed(2)}px`);
      el.style.setProperty("--look-y", `${((dy / d) * 1.5 * k).toFixed(2)}px`);
    };
    window.addEventListener("pointermove", move, { passive: true });
    return () => window.removeEventListener("pointermove", move);
  }, []);
  return (
    <span className="lib-keeper" aria-hidden>
      <span ref={eyes} className="cta-eyes">
        <i />
        <i />
      </span>
    </span>
  );
}

export function Library() {
  const cards = useLibrary((s) => s.cards);
  const ready = useLibrary((s) => s.ready);
  const unavailable = useLibrary((s) => s.unavailable);
  const [q, setQ] = useState("");
  // "2 min ago" is worked out when the list changes, which is when the page is looked at
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => setNow(Date.now()), [cards]);
  const shown = useMemo(() => {
    const t = q.trim().toLowerCase();
    return t ? cards.filter((c) => `${c.prompt} ${c.summary}`.toLowerCase().includes(t)) : cards;
  }, [cards, q]);
  const [latest, ...rest] = shown;
  const shelves = useMemo(() => {
    const out: { name: string; cards: LibraryCard[] }[] = [];
    for (const c of q ? shown : rest) {
      const name = shelfOf(c.updatedAt, now);
      const shelf = out.find((s) => s.name === name);
      if (shelf) shelf.cards.push(c);
      else out.push({ name, cards: [c] });
    }
    return out;
    // `rest` is derived from `shown`
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shown, q, now]);
  if (!ready) return null;
  let index = 0;
  return (
    <section className="library" aria-labelledby="lib-h">
      <header className="lib-head">
        <div className="lib-title-row">
          <Keeper />
          <h2 id="lib-h">Your drafts</h2>
          {cards.length > 0 && <span className="lib-count mono">{cards.length}</span>}
        </div>
        {cards.length > 3 && (
          <label className="lib-search">
            <svg viewBox="0 0 16 16" width="15" height="15" aria-hidden>
              <circle cx="7" cy="7" r="4.5" fill="none" stroke="currentColor" strokeWidth="1.6" />
              <path d="M10.5 10.5L14 14" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
            </svg>
            <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Find a draft" aria-label="Search your drafts" />
          </label>
        )}
      </header>
      {cards.length === 0 ? (
        <div className="lib-empty">
          <p>{unavailable ? "This browser isn't keeping storage, so builds can't be saved here." : "Nothing on the shelf yet."}</p>
          <button type="button" className="lib-pickup" onClick={() => useApp.setState({ screen: "home" })}>
            Start building
            <span className="cta-go" aria-hidden>
              <Icon name="send" size={14} />
            </span>
          </button>
        </div>
      ) : shown.length === 0 ? (
        <p className="lib-empty">Nothing matches “{q}”.</p>
      ) : (
        <>
          {!q && latest && <Latest card={latest} now={now} />}
          {shelves.map((s) => (
            <div className="lib-shelf" key={s.name}>
              <h3 className="lib-shelf-name mono">
                {s.name}
                <span>{s.cards.length}</span>
              </h3>
              <ul className="lib-grid">
                {s.cards.map((c) => (
                  <BuildCard key={c.build_id} card={c} now={now} index={index++} />
                ))}
              </ul>
            </div>
          ))}
        </>
      )}
    </section>
  );
}

/** A finished build's picture: its rendered product alone; the drawing from its own data only when no shot exists yet. */
function GalleryPicture(props: { item: GalleryItem }) {
  const { item } = props;
  const [broken, setBroken] = useState(false);
  if (item.shot && !broken) return <img className="lib-shot" src={item.shot} alt="" loading="lazy" decoding="async" onError={() => setBroken(true)} />;
  if (item.preview) return <BuildStill build={item.preview} className="gal-still" />;
  return item.thumb ? <img src={item.thumb} alt="" loading="lazy" /> : null;
}

export function GalleryCard(props: { item: GalleryItem; index?: number }) {
  const { item } = props;
  const [opening, setOpening] = useState(false);
  const open = async () => {
    // a bundled replay (engine library out of reach) is offered as a prompt to build again
    if (item.offline) {
      openBuildDialog(item.prompt.charAt(0).toLowerCase() + item.prompt.slice(1));
      return;
    }
    setOpening(true);
    await openLibraryBuild(item.build_id);
    setOpening(false);
  };
  return (
    <li className={`gal-card ${opening ? "opening" : ""}`} style={props.index != null ? { animationDelay: `${Math.min(props.index, 12) * 45}ms` } : undefined}>
      <button type="button" className="gal-open" onClick={() => void open()} aria-label={`Open the ${item.title.toLowerCase()} build`}>
        <span className="gal-thumb">
          <GalleryPicture item={item} />
        </span>
        <span className="gal-meta">
          <span className="gal-title">{item.title}</span>
          <span className="gal-sub">{item.checks} checks passed</span>
        </span>
      </button>
      {!item.offline && <Remove id={item.build_id} name={item.title} after={reloadGallery} />}
    </li>
  );
}

/** Library page: the finished builds (library/gallery.ts picks them) under a Build button, then the drafts. */
export function LibraryPage() {
  const items = useGallery((s) => s.items);
  const ready = useGallery((s) => s.ready);
  const drafts = useLibrary((s) => s.cards.length);
  useEffect(() => void loadGallery(), []);
  return (
    <div className="libpage">
      <header className="libpage-head">
        <div>
          <h1>Library</h1>
          <p className="muted">Finished builds. Every check held. Open one to look inside, or start your own.</p>
        </div>
        <button type="button" className="btn primary libpage-build" onClick={() => openBuildDialog()} aria-haspopup="dialog">
          Build
        </button>
      </header>
      <section className="gallery" aria-label="Finished builds">
        <ul className="gal-grid">
          {ready
            ? items.map((it, i) => <GalleryCard key={it.build_id} item={it} index={i} />)
            : [0, 1, 2, 3, 4, 5].map((i) => <li key={i} className="gal-card is-loading" aria-hidden />)}
        </ul>
      </section>
      <OpenSource />
      {drafts > 0 && <Library />}
      <Deleted />
    </div>
  );
}
