import { useEffect, useState } from "react";
import { useApp } from "../state/store";
import { deleteLibraryBuild, fetchLibrary, openLibraryBuild, type LibraryEntry } from "../net/client";
import { serverUrl } from "../net/mode";
import { Icon } from "../ui/common";

export function openLibrary(): void {
  useApp.setState({ libraryOpen: true });
}

function closeLibrary(): void {
  useApp.setState({ libraryOpen: false });
}

function when(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

/** Previous builds stored on the engine, the same list for every visitor. Open replays the recorded events. */
export function LibraryDialog() {
  const [rows, setRows] = useState<LibraryEntry[] | null>(null);
  const [confirm, setConfirm] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    void fetchLibrary().then((r) => live && setRows(r));
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && closeLibrary();
    window.addEventListener("keydown", onKey);
    return () => {
      live = false;
      window.removeEventListener("keydown", onKey);
    };
  }, []);

  const open = async (id: string) => {
    setBusy(id);
    if (!(await openLibraryBuild(id))) setBusy(null);
  };
  const remove = async (id: string) => {
    setBusy(id);
    if (await deleteLibraryBuild(id)) setRows((r) => (r ?? []).filter((x) => x.build_id !== id));
    setConfirm(null);
    setBusy(null);
  };

  return (
    <div className="modal-scrim" onMouseDown={(e) => e.target === e.currentTarget && closeLibrary()}>
      <div className="modal library" role="dialog" aria-label="Library">
        <header className="side-h">
          <div className="side-title">
            <h2>Library</h2>
            <span className="muted small">Previous builds, shared with everyone who opens this site</span>
          </div>
          <button type="button" className="btn ghost sm icon" aria-label="Close" onClick={closeLibrary}>
            <Icon name="x" />
          </button>
        </header>
        <div className="side-b library-list">
          {rows === null && <p className="muted small">Loading.</p>}
          {rows !== null && rows.length === 0 && <p className="muted small">No saved builds yet. Finished builds appear here.</p>}
          {(rows ?? []).map((r) => (
            <div key={r.build_id} className="library-row">
              <button type="button" className="library-open" disabled={busy === r.build_id} onClick={() => void open(r.build_id)} title="Open this build">
                <span className="library-thumb">{r.hero_url && <img src={serverUrl(r.hero_url)} alt="" loading="lazy" />}</span>
                <span className="library-text">
                  <span className="library-prompt">{r.prompt}</span>
                  <span className="muted small">
                    {[r.device, when(r.created_at)].filter(Boolean).join(" · ")}
                  </span>
                </span>
                <span className={`status-pill st-${r.status}`}>{r.status}</span>
              </button>
              {confirm === r.build_id ? (
                <span className="library-confirm">
                  <button type="button" className="btn danger sm" disabled={busy === r.build_id} onClick={() => void remove(r.build_id)}>
                    Delete
                  </button>
                  <button type="button" className="btn ghost sm" onClick={() => setConfirm(null)}>
                    Keep
                  </button>
                </span>
              ) : (
                <button type="button" className="btn ghost sm" onClick={() => setConfirm(r.build_id)} aria-label={`Delete ${r.prompt}`}>
                  Delete
                </button>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
