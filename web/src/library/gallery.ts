// The Library page's gallery: only finished builds from the engine's shared library, one per kind of
// device. "Finished" means the build ended done and no required check (error or critical) was
// still failing after its last repair round. The list itself (GET /v1/library) carries only the
// status, so the checks are read from each candidate's stored events, newest first per kind, and
// the verdict is kept in this browser (a stored build never changes).
import { create } from "zustand";
import { fetchLibrary, getRest, type StoredBuild } from "../net/client";
import { paths } from "../net/rest";
import { serverUrl } from "../net/mode";
import { distillEvents, type ReplayBuild } from "./replayData";
import landing from "./landingBuilds.json";

/** Product names never show on the landing; the device is described plainly instead. */
const BRANDS =
  /\s*\b(?:like an?\s+)?(?:nintendo\s+)?(?:game\s?boy(?:\s+advance|\s+color)?|gameboy|game\s+boy|switch\s+lite|playstation|xbox|steam\s+deck|stream\s+deck|ps[1-5]|nes|snes|tamagotchi|arduboy|flipper\s+zero)\b(?:[\s-]*style)?/gi;

export function scrubBrands(s: string): string {
  return s
    .replace(BRANDS, " ")
    .replace(/\s{2,}/g, " ")
    .replace(/\s+([,.])/g, "$1")
    .replace(/^\s*(?:a|an)\s*$/i, "")
    .trim();
}

/** The kind of device, for de-duplicating: "wireless game controller" and "game controller" are one kind. */
export function deviceKind(b: Pick<StoredBuild, "device" | "prompt">): string {
  const raw = scrubBrands((b.device || b.prompt || "").toLowerCase());
  return raw
    .replace(/\b(wireless|small|mini|tiny|cool|simple|desk|low-profile|mechanical|computer|\d+\s*(?:percent|%))(?=\s|$)/g, " ")
    .replace(/\s+with\b.*$/, "")
    .replace(/[^a-z ]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

export const capital = (s: string) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);

export interface GalleryItem {
  build_id: string;
  title: string;
  prompt: string;
  /** The build's rendered product alone on transparency (the main picture), when it has been shot. */
  shot: string | null;
  /** The engine's hero picture, when it made one. */
  thumb: string | null;
  /** Otherwise a drawing of the board and case from the build's own data. */
  preview: ReplayBuild | null;
  checks: number;
  /** Listed from the bundled replays because the engine's library was not reachable. */
  offline?: boolean;
}

/** Candidates per kind, in the order to try them: done builds, the ones with a picture first, newest first. */
export function candidatesByKind(builds: StoredBuild[]): StoredBuild[][] {
  const groups = new Map<string, StoredBuild[]>();
  for (const b of builds) {
    if (b.status !== "done") continue;
    const k = deviceKind(b);
    if (!k) continue;
    const g = groups.get(k) ?? [];
    g.push(b);
    groups.set(k, g);
  }
  const t = (b: StoredBuild) => (b.created_at ? Date.parse(b.created_at) || 0 : 0);
  return [...groups.values()]
    .map((g) => g.sort((a, b) => Number(!!b.shot_url) - Number(!!a.shot_url) || Number(!!b.hero_url) - Number(!!a.hero_url) || t(b) - t(a)))
    .sort((a, b) => t(b[0]) - t(a[0]));
}

interface Verdict {
  ok: boolean;
  checks: number;
  preview: ReplayBuild | null;
}

const KEY = "bara.gallery.v2.";

function cached(id: string): Verdict | null {
  try {
    const s = localStorage.getItem(KEY + id);
    return s ? (JSON.parse(s) as Verdict) : null;
  } catch {
    return null;
  }
}

function remember(id: string, v: Verdict): void {
  try {
    localStorage.setItem(KEY + id, JSON.stringify(v));
  } catch {
    // storage full or blocked: it is worked out again next visit
  }
}

async function verdict(b: StoredBuild): Promise<Verdict | null> {
  const hit = cached(b.build_id);
  if (hit) return hit;
  const res = await getRest().get<{ events: { type: string; payload: unknown }[] }>(paths.libraryBuild(b.build_id));
  if (!res.ok || !Array.isArray(res.body.events)) return null;
  const d = distillEvents(b.build_id, b.prompt, b.device ?? "", res.body.events);
  const v: Verdict = { ok: d.failed === 0, checks: d.checks, preview: b.hero_url || b.shot_url ? null : d };
  remember(b.build_id, v);
  return v;
}

/** Most kinds shown on the Library page. */
export const GALLERY_MAX = 9;

/** Picks, per kind, the newest candidate whose checks all held. */
export async function pickGallery(builds: StoredBuild[], judge: (b: StoredBuild) => Promise<Verdict | null> = verdict): Promise<GalleryItem[]> {
  const out: GalleryItem[] = [];
  for (const group of candidatesByKind(builds)) {
    if (out.length >= GALLERY_MAX) break;
    for (const b of group.slice(0, 4)) {
      const v = await judge(b).catch(() => null);
      if (!v?.ok) continue;
      const title = capital(scrubBrands(b.device || deviceKind(b)));
      out.push({ build_id: b.build_id, title, prompt: capital(scrubBrands(b.prompt)), shot: b.shot_url ? serverUrl(b.shot_url) : null, thumb: b.hero_url ? serverUrl(b.hero_url) : null, preview: v.preview, checks: v.checks });
      break;
    }
  }
  return out;
}

/** The bundled replays that finished cleanly, for when the engine's library cannot be read. */
export function offlineGallery(): GalleryItem[] {
  return (landing as ReplayBuild[])
    .filter((b) => b.failed === 0)
    .map((b) => ({ build_id: b.id, title: b.name, prompt: capital(b.prompt), shot: null, thumb: null, preview: b, checks: b.checks, offline: true }));
}

export const useGallery = create<{ items: GalleryItem[]; ready: boolean }>(() => ({ items: [], ready: false }));

let loading: Promise<void> | null = null;
export function loadGallery(): Promise<void> {
  loading ??= (async () => {
    const builds = await fetchLibrary().catch(() => []);
    const items = builds.length ? await pickGallery(builds) : [];
    useGallery.setState({ items: items.length ? items : offlineGallery(), ready: true });
  })();
  return loading;
}
