// Mock-mode switches (SPEC 13): ?mock=1 or VITE_MOCK=1, ?mock_speed, ?mock_fixture.
// ?server=https://host (or VITE_SERVER_URL) points at a remote server, e.g. a tunnel;
// it turns a VITE_MOCK build live unless ?mock=1 is also given. The deployed site finds the
// engine through /api/engine instead (see net/engine.ts).
export interface Mode {
  mock: boolean;
  speed: number;
  fixture: string | null;
  server: string | null;
}

export function readServer(raw: string | null | undefined): string | null {
  if (!raw) return null;
  try {
    const u = new URL(raw);
    return u.protocol === "https:" || u.protocol === "http:" ? u.origin : null;
  } catch {
    return null;
  }
}

export function readMode(search: string, env: { VITE_MOCK?: string; VITE_SERVER_URL?: string }): Mode {
  const q = new URLSearchParams(search);
  const server = readServer(q.get("server")) ?? readServer(env.VITE_SERVER_URL);
  const mock = q.get("mock") === "1" || (env.VITE_MOCK === "1" && !server);
  const rawSpeed = Number(q.get("mock_speed") ?? "1");
  const speed = Number.isFinite(rawSpeed) && rawSpeed > 0 ? rawSpeed : 1;
  const fixture = q.get("mock_fixture");
  return { mock, speed, fixture: fixture && /^[a-z0-9_]+$/.test(fixture) ? fixture : null, server };
}

// Shared access key for an engine exposed to the internet. ?key= saves it once, then it lives in
// this browser's storage. REST sends it as a header; sockets, GLB loads and downloads send ?token=.
const KEY_STORE = "engine.key";
let accessToken: string | null = null;
let currentServer: string | null = null;

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

let markReady: () => void = () => {};
const ready = new Promise<void>((resolve) => (markReady = resolve));

/** Resolves once the page knows which engine it talks to. On the deployed site that takes a lookup,
 *  and a request sent before it would go to the site itself and come back 404. */
export function serverReady(): Promise<void> {
  return ready;
}

export function setServer(server: string | null): void {
  currentServer = server;
  markReady();
}

export function readStoredKey(): string | null {
  try {
    return localStorage.getItem(KEY_STORE);
  } catch {
    return null;
  }
}

export function storeKey(key: string | null): void {
  try {
    if (key) localStorage.setItem(KEY_STORE, key);
    else localStorage.removeItem(KEY_STORE);
  } catch {
    // storage blocked: the key lasts for this page only
  }
}

/** Pull ?key= out of a query string. Returns the key (if any) and the query without it. */
export function splitKey(search: string): { key: string | null; search: string } {
  const q = new URLSearchParams(search);
  const key = q.get("key");
  q.delete("key");
  const rest = q.toString();
  return { key: key || null, search: rest ? `?${rest}` : "" };
}

export function authHeaders(): Record<string, string> {
  return accessToken ? { "x-bara-token": accessToken } : {};
}

export function withToken(url: string, token: string | null = accessToken): string {
  if (!token) return url;
  return `${url}${url.includes("?") ? "&" : "?"}token=${encodeURIComponent(token)}`;
}

/** Prefix a root-relative path ("/v1/...", "/assets/...") with the remote server origin. */
export function withServer(server: string | null, path: string): string {
  return server && path.startsWith("/") ? server + path : path;
}

/** A URL the browser fetches on its own (GLB loader, download link): server origin plus the key. */
export function serverUrl(path: string): string {
  if (!path.startsWith("/")) return path;
  return withToken(withServer(currentServer, path));
}

export function socketUrl(loc: { protocol: string; host: string }): string {
  return withToken(`${loc.protocol === "https:" ? "wss" : "ws"}://${loc.host}/v1/ws`);
}
