// Mock-mode switches (SPEC 13): ?mock=1 or VITE_MOCK=1, ?mock_speed, ?mock_fixture.
// ?server=https://host (or VITE_SERVER_URL) points at a remote server, e.g. a tunnel;
// it turns a VITE_MOCK build live unless ?mock=1 is also given.
export interface Mode {
  mock: boolean;
  speed: number;
  fixture: string | null;
  server: string | null;
}

function readServer(raw: string | null | undefined): string | null {
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

export function socketUrl(loc: { protocol: string; host: string }): string {
  return `${loc.protocol === "https:" ? "wss" : "ws"}://${loc.host}/v1/ws`;
}

/** Prefix a root-relative path ("/v1/...", "/assets/...") with the remote server origin. */
export function withServer(server: string | null, path: string): string {
  return server && path.startsWith("/") ? server + path : path;
}
