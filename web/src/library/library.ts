// Your builds (Figma 21 Home · your builds): every build is kept in this browser as it changes,
// with a snapshot of the canvas, so Home can list them and reopen any of them. IndexedDB, not
// localStorage: a finished build is a few hundred KB. Two stores: small cards for the list,
// full builds for reopening.
import { create } from "zustand";
import type { Build } from "../spec/types";
import type { ViewState } from "../state/view";

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
  mock: boolean;
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

export const useLibrary = create<{ cards: LibraryCard[]; ready: boolean; unavailable: boolean }>(() => ({
  cards: [],
  ready: false,
  unavailable: false,
}));

/** Reloads the list, newest first. */
export async function refreshLibrary(): Promise<void> {
  try {
    const d = await db();
    const cards = await done(d.transaction(CARDS).objectStore(CARDS).getAll() as IDBRequest<LibraryCard[]>);
    cards.sort((a, b) => b.updatedAt - a.updatedAt);
    useLibrary.setState({ cards, ready: true, unavailable: false });
  } catch {
    // private window or storage blocked: the library just stays empty
    useLibrary.setState({ cards: [], ready: true, unavailable: true });
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

export async function deleteEntry(buildId: string): Promise<void> {
  const d = await db();
  const tx = d.transaction([CARDS, BUILDS], "readwrite");
  tx.objectStore(CARDS).delete(buildId);
  tx.objectStore(BUILDS).delete(buildId);
  await new Promise<void>((resolve) => {
    tx.oncomplete = () => resolve();
  });
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
    return out.toDataURL("image/jpeg", 0.82);
  } catch {
    return null;
  }
}
