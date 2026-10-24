import { describe, expect, it } from "vitest";
import { discoverEngine } from "./engine";
import { serverUrl, setAccessToken, setServer, socketUrl, splitKey } from "./mode";

const ENGINE = "https://abc.trycloudflare.com";

function fake(routes: Record<string, () => Response>) {
  const seen: { url: string; init?: RequestInit }[] = [];
  const fn = async (url: string, init?: RequestInit) => {
    seen.push({ url, init });
    const hit = Object.entries(routes).find(([k]) => url.startsWith(k));
    if (!hit) throw new TypeError("network down");
    return hit[1]();
  };
  return { fn, seen };
}

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status });

describe("discoverEngine", () => {
  it("goes live without a key and sends none", async () => {
    const f = fake({ "/api/engine": () => json(200, { url: ENGINE }), [ENGINE]: () => json(200, {}) });
    expect(await discoverEngine(null, f.fn)).toEqual({ state: "live", url: ENGINE });
    expect(f.seen[0].init?.headers).toEqual({});
    expect(f.seen[1].url).toBe(`${ENGINE}/v1/vocab`);
  });

  it("is locked when the site rejects the key", async () => {
    const f = fake({ "/api/engine": () => json(401, {}) });
    expect((await discoverEngine("k", f.fn)).state).toBe("locked");
  });

  it("is offline when nothing is published", async () => {
    const f = fake({ "/api/engine": () => json(503, {}) });
    expect((await discoverEngine("k", f.fn)).state).toBe("offline");
  });

  it("is offline when the engine does not answer", async () => {
    const f = fake({ "/api/engine": () => json(200, { url: ENGINE }) });
    expect((await discoverEngine("k", f.fn)).state).toBe("offline");
  });

  it("goes live and sends the key to both hops", async () => {
    const f = fake({ "/api/engine": () => json(200, { url: ENGINE }), [ENGINE]: () => json(200, {}) });
    expect(await discoverEngine("k 1", f.fn)).toEqual({ state: "live", url: ENGINE });
    expect((f.seen[0].init?.headers as Record<string, string>)["x-bara-token"]).toBe("k 1");
    expect(f.seen[1].url).toBe(`${ENGINE}/v1/vocab?token=k%201`);
  });

  it("is locked when the engine rejects the key", async () => {
    const f = fake({ "/api/engine": () => json(200, { url: ENGINE }), [ENGINE]: () => json(401, {}) });
    expect((await discoverEngine("k", f.fn)).state).toBe("locked");
  });
});

describe("key and server URLs", () => {
  it("splits ?key= out of the query", () => {
    expect(splitKey("?key=abc&mock_speed=2")).toEqual({ key: "abc", search: "?mock_speed=2" });
    expect(splitKey("?key=abc")).toEqual({ key: "abc", search: "" });
    expect(splitKey("")).toEqual({ key: null, search: "" });
  });

  it("adds the server and key to loader and socket URLs", () => {
    setServer(ENGINE);
    setAccessToken("t");
    expect(serverUrl("/assets/a.glb")).toBe(`${ENGINE}/assets/a.glb?token=t`);
    expect(serverUrl("blob:x")).toBe("blob:x");
    expect(socketUrl(new URL(ENGINE))).toBe("wss://abc.trycloudflare.com/v1/ws?token=t");
    setServer(null);
    setAccessToken(null);
    expect(serverUrl("/v1/x")).toBe("/v1/x");
  });
});
