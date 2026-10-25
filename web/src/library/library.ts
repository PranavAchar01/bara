// Your builds (Figma 21 Home · your builds): every build is kept in this browser as it changes,
// with a snapshot of the canvas, so Home can list them and reopen any of them. IndexedDB, not
// localStorage: a finished build is a few hundred KB. Two stores: small cards for the list,
// full builds for reopening.
import { create } from "zustand";
import type { Build } from "../spec/types";
import type { ViewState } from "../state/view";
import { deleteLibraryBuild, fetchLibrary, getRest, type StoredBuild } from "../net/client";
import { paths } from "../net/rest";
import { serverUrl } from "../net/mode";

export interface LibraryCard {
  build_id: string;
  prompt: string;
  /** Short line under the prompt: the design it reused or the device, and the part count. */
  summary: string;
  status: string;
  parts: number;
  createdAt: number;
  updatedAt: number;
  /** JPEG data URL of the canvas, or null before the 3D view has drawn the build. */
  thumb: string | null;
  /** The product alone on transparency (the engine's rendered shot), preferred over the canvas snapshot. */
  shot?: string | null;
  mock: boolean;
  /** Listed from the engine's shared library, so it may have no copy in this browser. */
  remote?: boolean;
  /** Hidden from the library (deleted from view); every byte is kept and Restore shows it again. */
  hidden?: boolean;
}

export interface LibraryEntry {
  card: LibraryCard;
  build: Build;
  view: ViewState;
}

const DB = "bara-library";
const CARDS = "cards";
const BUILDS = "builds";
const MAX_ENTRIES = 60;

let dbp: Promise<IDBDatabase> | null = null;
function db(): Promise<IDBDatabase> {
  dbp ??= new Promise((resolve, reject) => {
    const req = indexedDB.open(DB, 1);
    req.onupgradeneeded = () => {
      req.result.createObjectStore(CARDS, { keyPath: "build_id" });
      req.result.createObjectStore(BUILDS);
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
  return dbp;
}

function done<T>(req: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

export const useLibrary = create<{ cards: LibraryCard[]; hidden: LibraryCard[]; ready: boolean; unavailable: boolean }>(() => ({
  cards: [],
  hidden: [],
  ready: false,
  unavailable: false,
}));

/** A card for a build stored on the engine, which every visitor of the site sees. */
export function remoteCard(b: StoredBuild): LibraryCard {
  const t = b.created_at ? Date.parse(b.created_at) : NaN;
  const at = Number.isNaN(t) ? 0 : t;
  const device = b.device ? b.device.charAt(0).toUpperCase() + b.device.slice(1) : "";
  return {
    build_id: b.build_id,
    prompt: b.prompt,
    summary: device,
    status: b.status === "done" ? "done" : "failed",
    parts: 0,
    createdAt: at,
    updatedAt: at,
    thumb: b.hero_url ? serverUrl(b.hero_url) : null,
    shot: b.shot_url ? serverUrl(b.shot_url) : null,
    mock: false,
    remote: true,
  };
}

/** Local cards plus the engine's shared library; a build in both shows once, with the local card. A build
 *  hidden here or on the engine (`hiddenIds`) is left out. */
export function mergeCards(local: LibraryCard[], remote: StoredBuild[], hiddenIds: ReadonlySet<string> = new Set()): LibraryCard[] {
  const have = new Map(local.map((c) => [c.build_id, c]));
  const out = local.filter((c) => !c.hidden && !hiddenIds.has(c.build_id)).map((c) => {
    const r = remote.find((x) => x.build_id === c.build_id);
    return r ? { ...c, remote: true, thumb: c.thumb ?? (r.hero_url ? serverUrl(r.hero_url) : null), shot: r.shot_url ? serverUrl(r.shot_url) : null } : c;
  });
  for (const r of remote) if (!have.has(r.build_id) && !hiddenIds.has(r.build_id)) out.push(remoteCard(r));
  return out.sort((a, b) => b.updatedAt - a.updatedAt);
}

/** Builds hidden on the engine; they come back with restoreEntry. */
async function fetchHidden(): Promise<StoredBuild[]> {
  const res = await getRest().get<{ builds: StoredBuild[] }>(paths.libraryHidden());
  // an engine from before hiding ignores ?hidden=1 and lists everything: only stamped rows count
  return res.ok && Array.isArray(res.body.builds) ? res.body.builds.filter((b) => b.hidden_at) : [];
}

/** The hidden list: engine rows hidden there, plus cards hidden in this browser only. */
export function hiddenCards(local: LibraryCard[], remoteHidden: StoredBuild[]): LibraryCard[] {
  const out: LibraryCard[] = remoteHidden.map((r) => ({ ...(local.find((c) => c.build_id === r.build_id) ?? remoteCard(r)), hidden: true }));
  for (const c of local) if (c.hidden && !out.some((o) => o.build_id === c.build_id)) out.push(c);
  return out.sort((a, b) => b.updatedAt - a.updatedAt);
}

/** Reloads the list, newest first: this browser's builds and the engine's shared library. */
export async function refreshLibrary(): Promise<void> {
  const [listed, remoteHidden] = await Promise.all([fetchLibrary().catch(() => []), fetchHidden().catch(() => [])]);
  const remote = listed.filter((b) => !b.hidden_at);
  const hiddenIds = new Set(remoteHidden.map((r) => r.build_id));
  try {
    const d = await db();
    const cards = await done(d.transaction(CARDS).objectStore(CARDS).getAll() as IDBRequest<LibraryCard[]>);
    useLibrary.setState({ cards: mergeCards(cards, remote, hiddenIds), hidden: hiddenCards(cards, remoteHidden), ready: true, unavailable: false });
  } catch {
    // private window or storage blocked: only the engine's shared builds are listed
    useLibrary.setState({ cards: mergeCards([], remote, hiddenIds), hidden: hiddenCards([], remoteHidden), ready: true, unavailable: remote.length === 0 });
  }
}

export async function saveEntry(entry: LibraryEntry): Promise<void> {
  const d = await db();
  const tx = d.transaction([CARDS, BUILDS], "readwrite");
  const cards = tx.objectStore(CARDS);
  const prev = await done(cards.get(entry.card.build_id) as IDBRequest<LibraryCard | undefined>);
  // keep the first time it was seen and the last good thumbnail
  const card = { ...entry.card, createdAt: prev?.createdAt ?? entry.card.createdAt, thumb: entry.card.thumb ?? prev?.thumb ?? null };
  cards.put(card);
  tx.objectStore(BUILDS).put({ build: entry.build, view: entry.view }, card.build_id);
  await new Promise<void>((resolve, reject) => {
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
  await prune();
  await refreshLibrary();
}

async function prune(): Promise<void> {
  const d = await db();
  const all = await done(d.transaction(CARDS).objectStore(CARDS).getAll() as IDBRequest<LibraryCard[]>);
  if (all.length <= MAX_ENTRIES) return;
  all.sort((a, b) => b.updatedAt - a.updatedAt);
  const tx = d.transaction([CARDS, BUILDS], "readwrite");
  for (const c of all.slice(MAX_ENTRIES)) {
    tx.objectStore(CARDS).delete(c.build_id);
    tx.objectStore(BUILDS).delete(c.build_id);
  }
}

export async function loadEntry(buildId: string): Promise<LibraryEntry | null> {
  const d = await db();
  const tx = d.transaction([CARDS, BUILDS]);
  const [card, saved] = await Promise.all([
    done(tx.objectStore(CARDS).get(buildId) as IDBRequest<LibraryCard | undefined>),
    done(tx.objectStore(BUILDS).get(buildId) as IDBRequest<{ build: Build; view: ViewState } | undefined>),
  ]);
  return card && saved ? { card, ...saved } : null;
}

/** Marks this browser's copy hidden (or shown again); the saved build itself is never removed. */
async function markLocal(buildId: string, hidden: boolean): Promise<void> {
  try {
    const d = await db();
    const tx = d.transaction(CARDS, "readwrite");
    const store = tx.objectStore(CARDS);
    const card = await done(store.get(buildId) as IDBRequest<LibraryCard | undefined>);
    if (card) store.put({ ...card, hidden });
    await new Promise<void>((resolve) => {
      tx.oncomplete = () => resolve();
      tx.onerror = () => resolve();
    });
  } catch {
    // storage blocked: nothing local to mark
  }
}

/** Deletes a build from the library's view, here and on the engine. Soft: nothing is erased, restoreEntry undoes it. */
export async function deleteEntry(buildId: string): Promise<void> {
  await deleteLibraryBuild(buildId);
  await markLocal(buildId, true);
  await refreshLibrary();
}

/** Brings a deleted build back, here and on the engine. */
export async function restoreEntry(buildId: string): Promise<void> {
  await getRest().request("POST", paths.libraryRestore(buildId));
  await markLocal(buildId, false);
  await refreshLibrary();
}

/** The card's short line: the design it reused or the kind of device, and how many parts. */
export function summarize(build: Build, view: ViewState): string {
  const parts = build.parts.reduce((n, p) => n + (p.quantity || 1), 0);
  const r = view.reuse;
  const design = r?.design?.name ?? r?.considered?.find((c) => c.design_id === r.design_id)?.name ?? null;
  const kind = build.spec?.device_class ? build.spec.device_class.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase()) : null;
  return [design ?? kind, parts ? `${parts} parts` : null].filter(Boolean).join(" · ");
}

/** True when a picture is one flat colour: a canvas grabbed before the 3D view had drawn anything. */
export function isFlat(src: CanvasImageSource, w: number, h: number): boolean {
  const c = document.createElement("canvas");
  c.width = 32;
  c.height = 20;
  const ctx = c.getContext("2d", { willReadFrequently: true });
  if (!ctx || !w || !h) return false;
  try {
    ctx.drawImage(src, 0, 0, w, h, 0, 0, 32, 20);
    const d = ctx.getImageData(0, 0, 32, 20).data;
    let min = 255;
    let max = 0;
    for (let i = 0; i < d.length; i += 4) {
      const v = (d[i] + d[i + 1] + d[i + 2]) / 3;
      if (v < min) min = v;
      if (v > max) max = v;
    }
    return max - min < 6;
  } catch {
    // a picture from elsewhere that can't be read back: trust it
    return false;
  }
}

/** A small JPEG of the 3D canvas, cropped to the card's 16:10, or null when there is nothing drawn. */
export function snapshotCanvas(canvas: HTMLCanvasElement | null, width = 480, height = 300): string | null {
  if (!canvas || !canvas.width || !canvas.height) return null;
  const out = document.createElement("canvas");
  out.width = width;
  out.height = height;
  const ctx = out.getContext("2d");
  if (!ctx) return null;
  const want = width / height;
  const have = canvas.width / canvas.height;
  const sw = have > want ? canvas.height * want : canvas.width;
  const sh = have > want ? canvas.height : canvas.width / want;
  try {
    ctx.fillStyle = "#f6f6f5";
    ctx.fillRect(0, 0, width, height);
    ctx.drawImage(canvas, (canvas.width - sw) / 2, (canvas.height - sh) / 2, sw, sh, 0, 0, width, height);
    if (isFlat(out, width, height)) return null;
    return out.toDataURL("image/jpeg", 0.82);
  } catch {
    return null;
  }
}
