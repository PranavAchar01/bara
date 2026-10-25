import { describe, expect, it, vi } from "vitest";
import { cachedLoad } from "./assets";
import { boardBadge } from "./board";

describe("cachedLoad", () => {
  it("shares one load per key and keeps a success", async () => {
    const store = new Map<string, Promise<number | null>>();
    const load = vi.fn(() => Promise.resolve(7));
    const [a, b] = await Promise.all([cachedLoad(store, "k", load, 1000), cachedLoad(store, "k", load, 1000)]);
    expect([a, b]).toEqual([7, 7]);
    expect(load).toHaveBeenCalledTimes(1);
    expect(store.has("k")).toBe(true);
  });

  it("drops a failure from the cache so the next ask fetches again", async () => {
    const store = new Map<string, Promise<number | null>>();
    const load = vi.fn().mockRejectedValueOnce(new Error("net")).mockResolvedValueOnce(3);
    expect(await cachedLoad(store, "k", load, 1000)).toBeNull();
    expect(store.has("k")).toBe(false);
    expect(await cachedLoad(store, "k", load, 1000)).toBe(3);
    expect(load).toHaveBeenCalledTimes(2);
  });

  it("gives up on a load that never settles", async () => {
    vi.useFakeTimers();
    try {
      const store = new Map<string, Promise<number | null>>();
      const p = cachedLoad(store, "k", () => new Promise<number>(() => {}), 30_000);
      await vi.advanceTimersByTimeAsync(30_000);
      expect(await p).toBeNull();
      expect(store.has("k")).toBe(false);
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("boardBadge", () => {
  const base = { boardStatus: "ok", model: { status: "ready" }, buildOver: false, boardStage: "ok", playing: false };

  it("says routing only while the board stage can still deliver", () => {
    expect(boardBadge({ ...base, boardStatus: "pending", boardStage: "active" })?.text).toBe("Routing on KiCad");
    expect(boardBadge({ ...base, boardStatus: "pending", boardStage: "failed" })).toBeNull();
    expect(boardBadge({ ...base, boardStatus: "pending", boardStage: "active", buildOver: true })).toBeNull();
  });

  it("shows loading, then a retry once the model failed", () => {
    expect(boardBadge({ ...base, model: { status: "loading" } })?.text).toBe("Loading 3D board");
    const retry = vi.fn();
    const b = boardBadge({ ...base, model: { status: "failed", retry } });
    expect(b?.retry).toBe(retry);
    expect(boardBadge(base)).toBeNull();
  });

  it("never shows a badge in play mode", () => {
    expect(boardBadge({ ...base, boardStatus: "pending", boardStage: "active", playing: true })).toBeNull();
    expect(boardBadge({ ...base, model: { status: "loading" }, playing: true })).toBeNull();
  });
});
