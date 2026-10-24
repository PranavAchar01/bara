import { describe, expect, it } from "vitest";
import { RestClient, paths } from "./rest";
import { mergeCards, type LibraryCard } from "../library/library";

const local = (id: string, at: number): LibraryCard => ({
  build_id: id,
  prompt: id,
  summary: "",
  status: "done",
  parts: 1,
  createdAt: at,
  updatedAt: at,
  thumb: null,
  mock: false,
});
const stored = (id: string, at: string) => ({
  build_id: id,
  prompt: id,
  device: "game console",
  created_at: at,
  status: "done" as const,
  hero_url: `/assets/cache/hero/${id}.png`,
});

describe("library merge", () => {
  it("lists engine builds once, newest first, and fills a missing thumbnail", () => {
    const cards = mergeCards([local("b_a", 2000)], [stored("b_a", "1970-01-01T00:00:01Z"), stored("b_b", "1970-01-01T00:00:09Z")]);
    expect(cards.map((c) => c.build_id)).toEqual(["b_b", "b_a"]);
    expect(cards[0].remote).toBe(true);
    expect(cards[0].summary).toBe("Game console");
    expect(cards[1].thumb).toContain("b_a.png");
  });

  it("is just the local list when the engine has none (mock mode)", () => {
    expect(mergeCards([local("b_a", 1)], []).map((c) => c.build_id)).toEqual(["b_a"]);
  });
});

describe("library rest", () => {
  it("encodes the build id and uses DELETE", async () => {
    const seen: string[] = [];
    const rc = new RestClient(async (method, path) => {
      seen.push(`${method} ${path}`);
      return { status: 200, body: { deleted: "b_x" } };
    });
    expect((await rc.delete(paths.libraryBuild("b_x"))).ok).toBe(true);
    expect(seen).toEqual(["DELETE /v1/library/b_x"]);
    expect(paths.libraryBuild("../x")).toBe("/v1/library/..%2Fx");
  });

  it("reports failure when the stub has no library (callers show an empty list)", async () => {
    const rc = new RestClient(async () => ({
      status: 404,
      body: { error: { code: "E_NOT_FOUND", message: "x", retryable: false } },
    }));
    expect((await rc.get(paths.library())).ok).toBe(false);
  });
});
