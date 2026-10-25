// Open-source boards on the Library page, ported from Etch's Explore: real KiCad projects from GitHub with
// category chips, search, a "Copyable only" licence switch and a sort. Opening one shows its credits (who
// made it, which commit, which licence, both linked: the licences ask for that), what it is made of, and
// a one-line "what is this part" for every part, taken from the board's own part descriptions, beside an
// interactive 3D view of the board itself (LibraryBoard3D) where picking a part lights it.
import { useEffect, useMemo, useRef, useState } from "react";
import "../styles/opensource.css";
import { LibraryBoard3D } from "./LibraryBoard3D";
import { capital, filterBoards, loadOpenSource, loadParts, scrubMakers, thumbUrl, useOpenSource, type OsBoard, type OsPart, type OsSort } from "../library/openSource";

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
  return <span className={`os-lic ${b.copyable ? "ok" : "view"}`}>{b.license ?? "No licence"}</span>;
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

function BoardDetail({ b, onClose }: { b: OsBoard; onClose: () => void }) {
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
            <p className={`os-licnote ${b.copyable ? "ok" : "view"}`}>
              {b.copyable
                ? `${b.license} lets you copy and adapt this board, as long as you keep the credit above.`
                : `${b.license ?? "No licence"} does not allow copying, so this one is for looking only.`}
            </p>
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
  const [copyableOnly, setCopyableOnly] = useState(false);
  const [sort, setSort] = useState<OsSort>("popular");
  const [all, setAll] = useState(false);
  const [open, setOpen] = useState<OsBoard | null>(null);
  useEffect(() => void loadOpenSource(), []);
  const list = useMemo(() => filterBoards(boards, { q, category, copyableOnly, sort }), [boards, q, category, copyableOnly, sort]);
  if (ready && (failed || boards.length === 0)) return null;
  const narrowed = !!(q || category || copyableOnly);
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
          <button type="button" className={`os-sw ${copyableOnly ? "on" : ""}`} role="switch" aria-checked={copyableOnly} onClick={() => setCopyableOnly((v) => !v)}>
            <span className="os-knob" />
            Copyable only
          </button>
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
        {!ready ? [0, 1, 2, 3].map((i) => <li key={i} className="gal-card is-loading" aria-hidden />) : visible.map((b) => <BoardCard key={b.id} b={b} onOpen={() => setOpen(b)} />)}
      </ul>
      {ready && list.length === 0 && <p className="muted">No board matches.</p>}
      {ready && !all && !narrowed && list.length > FIRST && (
        <button type="button" className="btn sm os-more" onClick={() => setAll(true)}>
          See all {list.length}
        </button>
      )}
      {open && <BoardDetail b={open} onClose={() => setOpen(null)} />}
    </section>
  );
}
