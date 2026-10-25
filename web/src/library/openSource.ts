// Open-source boards: real KiCad projects from GitHub, drawn from Etch's board library (same data, same
// licence fields). Browsing needs no engine: the index and a still per board are static files under
// /explore. A board's parts are fetched only when it is opened. Maker names never reach the screen:
// titles, repo names, footprints and part descriptions go through scrubMakers.
import { create } from "zustand";

export interface OsBoard {
  id: string;
  slug: string;
  title: string;
  owner: string;
  repo: string;
  category: string;
  stars: number;
  license: string | null;
  copyable: boolean;
  layers: number;
  size_mm: [number, number] | null;
  parts: number;
  url: string | null;
  commit: string | null;
  license_url: string | null;
  description: string | null;
  topics: string[] | null;
  thumb: boolean;
}

export interface OsCategory {
  id: string;
  label: string;
  count: number;
}

/** [ref, value, footprint, description, side, pos_mm, rot] */
export type OsPartRow = [string, string, string, string, string, [number, number] | null, number | null];

export interface OsPart {
  ref: string;
  value: string;
  footprint: string;
  what: string;
  side: string;
  pos: [number, number] | null;
  rot: number | null;
}

const MAKERS =
  /\b(cherry|kailh|gateron|alps|panasonic|jst|molex|amphenol|te connectivity|w[uü]rth|murata|texas instruments|nordic|espressif|stmicroelectronics|microchip|atmel|infineon|nxp|analog devices|maxim|diodes inc|vishay|yageo|samsung|tdk|omron|e-switch|apem|nichicon|wiznet|silicon labs|raspberry pi|adafruit|sparkfun|seeed|xiao|arduino|pimoroni|ebyte|ai-thinker|hoperf|semtech|lite-on|everlight|worldsemi|cree|osram|bourns|littelfuse|knowles|invensense|bosch|sensirion|lattice|xilinx|altera|rohm|toshiba|onsemi|fairchild|linear technology|wch|winbond|macronix|gigadevice|ftdi)\b[\s_-]*/gi;

/** Takes maker names out of text shown on screen. The link behind a credit keeps the real repo path. */
export function scrubMakers(s: string): string {
  return s
    .replace(/https?:\/\/\S+/g, "")
    .replace(MAKERS, "")
    .replace(/\s{2,}/g, " ")
    .replace(/^[\s_\-·,;:]+|[\s_\-·,;:]+$/g, "")
    .trim();
}

export function capital(s: string): string {
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : s;
}

/** A footprint's package, without the library prefix or a maker: "Package_SO:SOIC-16_3.9x9.9mm" -> "SOIC-16 3.9x9.9mm". */
export function packageName(fp: string): string {
  const tail = fp.split(":").pop() ?? fp;
  return scrubMakers(tail.replace(/_/g, " ")) || "Custom footprint";
}

export function firstSentence(t: string): string {
  const clean = scrubMakers(t.replace(/`/g, "")).replace(/\s+/g, " ");
  const m = clean.match(/^.*?[.!?](?=\s|$)/);
  return capital((m ? m[0] : clean).slice(0, 140));
}

/** What a part is, in one line, from its own description (or its package when it has none). */
export function toPart(r: OsPartRow): OsPart {
  const what = firstSentence(r[3] || "");
  return {
    ref: r[0],
    value: scrubMakers(r[1]).replace(/^VAL\*+$/, ""),
    footprint: packageName(r[2]),
    what: what || `A ${packageName(r[2])} part.`,
    side: r[4],
    pos: r[5],
    rot: r[6],
  };
}

export type OsSort = "popular" | "parts";

export function filterBoards(boards: OsBoard[], o: { q: string; category: string | null; copyableOnly: boolean; sort: OsSort }): OsBoard[] {
  const q = o.q.trim().toLowerCase();
  const out = boards.filter((b) => {
    if (o.category && b.category !== o.category) return false;
    if (o.copyableOnly && !b.copyable) return false;
    if (!q) return true;
    return [b.title, b.owner, b.repo, b.license ?? "", b.description ?? ""].join(" ").toLowerCase().includes(q);
  });
  return out.sort((a, b) => (o.sort === "parts" ? b.parts - a.parts : b.stars - a.stars) || a.title.localeCompare(b.title));
}

interface State {
  boards: OsBoard[];
  categories: OsCategory[];
  ready: boolean;
  failed: boolean;
}

export const useOpenSource = create<State>(() => ({ boards: [], categories: [], ready: false, failed: false }));

let loading: Promise<void> | null = null;
export function loadOpenSource(): Promise<void> {
  loading ??= fetch("/explore/index.json")
    .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
    .then((d: { boards: OsBoard[]; categories: OsCategory[] }) => useOpenSource.setState({ boards: d.boards, categories: d.categories, ready: true }))
    .catch(() => useOpenSource.setState({ ready: true, failed: true }));
  return loading;
}

export async function loadParts(slug: string): Promise<OsPart[]> {
  const r = await fetch(`/explore/parts/${encodeURIComponent(slug)}.json`);
  if (!r.ok) throw new Error(String(r.status));
  return ((await r.json()) as OsPartRow[]).map(toPart);
}

export const thumbUrl = (b: Pick<OsBoard, "slug">) => `/explore/thumb/${encodeURIComponent(b.slug)}.webp`;

/** Where a board's 3D model is read from, in order: this site's own copy under /explore/glb (put there by
 *  scripts/sync-board-glbs.mjs, not committed: the set is ~150 MB), then the board library's published copy,
 *  which is the same file and is served with open CORS. */
export const BOARD_GLB_REMOTE = "https://etch.chat/world/boards";
export function boardGlbUrls(slug: string): string[] {
  const s = encodeURIComponent(slug);
  return [`/explore/glb/${s}.glb`, `${BOARD_GLB_REMOTE}/${s}/board.glb`];
}
