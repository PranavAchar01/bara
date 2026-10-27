// Open-source boards on the Library page, ported from Etch's Explore: real KiCad projects from GitHub with
// category chips, search and a sort. Opening one shows its credits (who
// made it, which commit, which licence, both linked: the licences ask for that), what it is made of, and
// a one-line "what is this part" for every part, taken from the board's own part descriptions, beside an
// interactive 3D view of the board itself (LibraryBoard3D) where picking a part lights it.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import "../styles/opensource.css";
import { LibraryBoard3D } from "./LibraryBoard3D";
import { openLibraryBuild } from "../net/client";
import { capital, filterBoards, importBoard, loadOpenSource, loadParts, scrubMakers, thumbUrl, useOpenSource, type OsBoard, type OsPart, type OsSort } from "../library/openSource";

const FIRST = 8;

function Credit({ b }: { b: OsBoard }) {
  const href = b.url ? b.url + (b.commit ? `/tree/${b.commit}` : "") : `https://github.com/${b.owner}/${b.repo}`;
  return (
    <p className="os-credit">
      From{" "}
      <a href={href} target="_blank" rel="noopener noreferrer">
        {scrubMakers(`${b.owner}/${b.repo}`) || b.owner}
      </a>
      {b.commit && <span className="mono"> @ {b.commit.slice(0, 7)}</span>}
      {" · "}
      {b.license ? (
        b.license_url ? (
          <a href={b.license_url} target="_blank" rel="noopener noreferrer">
            {b.license}
          </a>
        ) : (
          b.license
        )
      ) : (
        "No licence"
      )}
    </p>
  );
}

function Licence({ b }: { b: Pick<OsBoard, "license" | "copyable"> }) {
  return <span className="os-lic ok">{b.license ?? "No licence"}</span>;
}

function BoardCard({ b, onOpen }: { b: OsBoard; onOpen: () => void }) {
  const cat = useOpenSource((s) => s.categories.find((c) => c.id === b.category)?.label ?? "");
  return (
    <li className="gal-card os-card">
      <button type="button" className="gal-open" onClick={onOpen} aria-label={`Open ${scrubMakers(b.title)}`}>
        <span className="gal-thumb">{b.thumb && <img src={thumbUrl(b)} alt="" loading="lazy" />}</span>
        <span className="gal-meta">
          <span className="gal-title">{scrubMakers(b.title)}</span>
          <span className="gal-sub">
            {cat} · {b.parts} parts
          </span>
          <Licence b={b} />
        </span>
      </button>
    </li>
  );
}

function PartInfo({ p }: { p: OsPart }) {
  return (
    <div className="os-info" aria-live="polite">
      <b>{p.ref}</b>
      {p.value && <span className="os-info-v"> · {p.value}</span>}
      <p>{p.what}</p>
      <dl>
        <dt>Package</dt>
        <dd>{p.footprint}</dd>
        <dt>Side</dt>
        <dd>{p.side || "top"}</dd>
        {p.pos && (
          <>
            <dt>Position</dt>
            <dd>
              {p.pos[0].toFixed(1)}, {p.pos[1].toFixed(1)} mm
            </dd>
          </>
        )}
        {p.rot != null && (
          <>
            <dt>Rotation</dt>
            <dd>{Math.round(p.rot)}°</dd>
          </>
        )}
      </dl>
    </div>
  );
}

/** Where opening a board as a build stands: still opening, or failed with the reason and a retry. */
export type OpenState = { state: "opening" } | { state: "failed"; message: string };

function BoardDetail({ b, onClose, opening, onRetry }: { b: OsBoard; onClose: () => void; opening?: OpenState; onRetry?: () => void }) {
  const [parts, setParts] = useState<OsPart[] | null>(null);
  const [err, setErr] = useState(false);
  const [sel, setSel] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const closeRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    let live = true;
    loadParts(b.slug).then((p) => live && setParts(p), () => live && setErr(true));
    closeRef.current?.focus();
    const key = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", key);
    return () => {
      live = false;
      window.removeEventListener("keydown", key);
    };
  }, [b.slug, onClose]);
  const shown = useMemo(() => {
    const t = q.trim().toLowerCase();
    return (parts ?? []).filter((p) => !t || `${p.ref} ${p.value} ${p.footprint} ${p.what}`.toLowerCase().includes(t));
  }, [parts, q]);
  const picked = parts?.find((p) => p.ref === sel) ?? null;
  const refs = useMemo(() => new Set((parts ?? []).map((p) => p.ref)), [parts]);
  const size = b.size_mm ? `${b.size_mm[0].toFixed(0)} × ${b.size_mm[1].toFixed(0)} mm` : null;
  return (
    <div className="modal-scrim" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal os-detail" role="dialog" aria-label={scrubMakers(b.title)}>
        <header className="os-d-head">
          <div>
            <h2>{scrubMakers(b.title)}</h2>
            <Credit b={b} />
          </div>
          <button ref={closeRef} type="button" className="btn sm" onClick={onClose}>
            Close
          </button>
        </header>
        {opening && (
          <div className={`os-opening ${opening.state}`} role="status">
            {opening.state === "opening" ? (
              <span>Opening it as a build you can edit…</span>
            ) : (
              <>
                <span>It could not open as a build: {opening.message}</span>
                {onRetry && (
                  <button type="button" className="btn sm" onClick={onRetry}>
                    Try again
                  </button>
                )}
              </>
            )}
          </div>
        )}
        <div className="os-d-body">
          <div className="os-d-left">
            <LibraryBoard3D slug={b.slug} title={scrubMakers(b.title)} refs={refs} selected={sel} onPick={setSel} poster={b.thumb ? thumbUrl(b) : undefined} />
            {b.description && <p className="os-desc">{capital(scrubMakers(b.description))}</p>}
            <ul className="os-facts">
              <li>{b.parts} parts</li>
              <li>{b.layers} layers</li>
              {size && <li>{size}</li>}
              {b.stars > 0 && <li>{b.stars.toLocaleString()} stars</li>}
            </ul>
            <p className="os-licnote ok">Copy and adapt this board, and keep the credit above.</p>
          </div>
          <div className="os-d-right">
            <input className="os-search" type="search" placeholder="Find a part" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Find a part" />
            {picked && <PartInfo p={picked} />}
            {err ? (
              <p className="muted small">This board's parts could not be loaded.</p>
            ) : !parts ? (
              <p className="muted small">Loading parts…</p>
            ) : (
              <ul className="os-parts">
                {shown.slice(0, 200).map((p) => (
                  <li key={p.ref}>
                    <button type="button" className={p.ref === sel ? "on" : ""} onClick={() => setSel(p.ref === sel ? null : p.ref)}>
                      <b>{p.ref}</b>
                      <span>{p.value || p.footprint}</span>
                    </button>
                  </li>
                ))}
                {shown.length > 200 && <li className="muted small">{shown.length - 200} more, narrow the search</li>}
                {shown.length === 0 && <li className="muted small">No part matches.</li>}
              </ul>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export function OpenSource() {
  const { boards, categories, ready, failed } = useOpenSource();
  const [q, setQ] = useState("");
  const [category, setCategory] = useState<string | null>(null);
  const [sort, setSort] = useState<OsSort>("popular");
  const [all, setAll] = useState(false);
  const [open, setOpen] = useState<OsBoard | null>(null);
  const [opening, setOpening] = useState<OpenState | undefined>(undefined);
  const [showDetail, setShowDetail] = useState(false);
  const attempt = useRef(0);
  // An open-source board opens in the same workspace as any build: it is imported once (its own KiCad
  // files become a build on the engine) and then opened by id. The 3D look-only view shows only while a
  // first import takes a while, or when it fails, with a retry.
  const openBoard = (b: OsBoard) => {
    const n = ++attempt.current;
    setOpen(b);
    setOpening({ state: "opening" });
    setShowDetail(false);
    const slow = window.setTimeout(() => n === attempt.current && setShowDetail(true), 700);
    void importBoard(b.slug).then(async (r) => {
      window.clearTimeout(slow);
      if (n !== attempt.current) return;
      if (r.ok && (await openLibraryBuild(r.buildId))) {
        setOpen(null);
        setOpening(undefined);
        return;
      }
      setOpening({ state: "failed", message: r.ok ? "the build did not load" : r.message });
      setShowDetail(true);
    });
  };
  const closeDetail = useCallback(() => {
    attempt.current++;
    setOpen(null);
    setOpening(undefined);
  }, []);
  useEffect(() => void loadOpenSource(), []);
  const list = useMemo(() => filterBoards(boards, { q, category, sort }), [boards, q, category, sort]);
  if (ready && (failed || boards.length === 0)) return null;
  const narrowed = !!(q || category);
  const visible = all || narrowed ? list : list.slice(0, FIRST);
  return (
    <section className="os" aria-label="Open-source boards">
      <header className="os-head">
        <div>
          <h2>Open-source boards</h2>
          <p className="muted">Real KiCad projects from GitHub, with their licences. Open one to see who made it and what every part does.</p>
        </div>
        <div className="os-tools">
          <input className="os-search" type="search" placeholder="Title, owner, repo" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search boards" />
          <select className="os-sort" value={sort} onChange={(e) => setSort(e.target.value as OsSort)} aria-label="Sort">
            <option value="popular">Popular</option>
            <option value="parts">Most parts</option>
          </select>
        </div>
      </header>
      <div className="os-cats" role="group" aria-label="Categories">
        <button type="button" className={!category ? "on" : ""} onClick={() => setCategory(null)}>
          All <span>{boards.length}</span>
        </button>
        {categories
          .filter((c) => c.count > 0)
          .map((c) => (
            <button key={c.id} type="button" className={category === c.id ? "on" : ""} onClick={() => setCategory(category === c.id ? null : c.id)}>
              {c.label} <span>{c.count}</span>
            </button>
          ))}
      </div>
      <ul className="gal-grid">
        {!ready ? [0, 1, 2, 3].map((i) => <li key={i} className="gal-card is-loading" aria-hidden />) : visible.map((b) => <BoardCard key={b.id} b={b} onOpen={() => openBoard(b)} />)}
      </ul>
      {ready && list.length === 0 && <p className="muted">No board matches.</p>}
      {ready && !all && !narrowed && list.length > FIRST && (
        <button type="button" className="btn sm os-more" onClick={() => setAll(true)}>
          See all {list.length}
        </button>
      )}
      {open && showDetail && <BoardDetail b={open} onClose={closeDetail} opening={opening} onRetry={() => openBoard(open)} />}
    </section>
  );
}
