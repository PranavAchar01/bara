// REST client (SPEC 7). In mock mode the same calls are answered from
// spec/fixtures/rest by method and path (SPEC 13).
import type { ErrorObject, ErrorResponse, RestFixture } from "../spec/types";
import { SPEC_VERSION } from "../spec/types";
import { authHeaders, withServer } from "./mode";
import { fixtureBuildPath } from "./fakeSocket";

export type RestResult<T> = { ok: true; status: number; body: T } | { ok: false; status: number; error: ErrorObject };

export type Fetcher = (method: "GET" | "POST" | "DELETE", path: string, body?: unknown) => Promise<{ status: number; body: unknown }>;

export const httpFetcher = (server: string | null): Fetcher => async (method, path, body) => {
  const res = await fetch(withServer(server, path), {
    method,
    headers: body === undefined ? authHeaders() : { "content-type": "application/json", ...authHeaders() },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let parsed: unknown = null;
  try {
    parsed = await res.json();
  } catch {
    parsed = null;
  }
  return { status: res.status, body: parsed };
};

function pathOnly(p: string): string {
  const q = p.indexOf("?");
  const raw = q >= 0 ? p.slice(0, q) : p;
  try {
    return decodeURIComponent(raw);
  } catch {
    return raw;
  }
}

/** Fixture-backed fetcher: match by method and path, otherwise E_NOT_FOUND. */
export function stubFetcher(fixtures: RestFixture[]): Fetcher {
  return async (method, path) => {
    const want = fixtureBuildPath(pathOnly(path));
    const hit = fixtures.find((f) => f.request.method === method && pathOnly(f.request.path) === want);
    if (hit) return { status: hit.response.status, body: JSON.parse(JSON.stringify(hit.response.body)) as unknown };
    const body: ErrorResponse = {
      spec_version: SPEC_VERSION,
      error: { code: "E_NOT_FOUND", message: `No mock response for ${method} ${want}.`, retryable: false },
    };
    return { status: 404, body };
  };
}

export class RestClient {
  private readonly fetcher: Fetcher;
  constructor(fetcher: Fetcher) {
    this.fetcher = fetcher;
  }

  async request<T>(method: "GET" | "POST" | "DELETE", path: string, body?: unknown): Promise<RestResult<T>> {
    try {
      const res = await this.fetcher(method, path, body);
      if (res.status >= 400) {
        const err = (res.body as ErrorResponse | null)?.error;
        return {
          ok: false,
          status: res.status,
          error: err ?? { code: "E_UNKNOWN", message: `HTTP ${res.status}`, retryable: true },
        };
      }
      return { ok: true, status: res.status, body: res.body as T };
    } catch (e) {
      return {
        ok: false,
        status: 0,
        error: { code: "E_INTERNAL", message: e instanceof Error ? e.message : "Network error", retryable: true },
      };
    }
  }

  get<T>(path: string): Promise<RestResult<T>> {
    return this.request<T>("GET", path);
  }

  delete<T>(path: string): Promise<RestResult<T>> {
    return this.request<T>("DELETE", path);
  }
}

export const paths = {
  health: () => "/v1/health",
  vocab: () => "/v1/vocab",
  library: () => "/v1/library",
  libraryBuild: (id: string) => `/v1/library/${encodeURIComponent(id)}`,
  libraryShot: (id: string) => `/v1/library/${encodeURIComponent(id)}/shot`,
  build: (id: string) => `/v1/builds/${encodeURIComponent(id)}`,
  events: (id: string, afterSeq = 0) => `/v1/builds/${encodeURIComponent(id)}/events?after_seq=${afterSeq}`,
  part: (partId: string) => `/v1/parts/${encodeURIComponent(partId)}`,
  parts: (q: string) => `/v1/parts${q ? `?q=${encodeURIComponent(q)}` : ""}`,
  design: (id: string) => `/v1/designs/${encodeURIComponent(id)}`,
  alternatives: (buildId: string, slotId: string, instanceId?: string) =>
    `/v1/builds/${encodeURIComponent(buildId)}/slots/${encodeURIComponent(slotId)}/alternatives${
      instanceId ? `?instance_id=${encodeURIComponent(instanceId)}` : ""
    }`,
  export: (buildId: string, format: string) =>
    `/v1/builds/${encodeURIComponent(buildId)}/export?format=${encodeURIComponent(format)}`,
};
