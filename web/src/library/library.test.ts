import { describe, expect, it } from "vitest";
import { hiddenCards, mergeCards, summarize, type LibraryCard } from "./library";
import type { StoredBuild } from "../net/client";
import { emptyView } from "../state/view";
import type { Build } from "../spec/types";

const build = (over: Partial<Build>): Build =>
  ({ build_id: "b", prompt: "a keyboard", status: "done", parts: [], decisions: [], revision: 0, warnings: [], ...over }) as unknown as Build;

describe("library card summary", () => {
  it("names the reused design and counts every piece", () => {
    const view = { ...emptyView(), reuse: { tier: "exact", design_id: "corne", design: { name: "Corne (crkbd)" }, considered: [], unmet_hard: [], reason: "" } } as never;
    const b = build({ parts: [{ quantity: 42 }, { quantity: 1 }] as never });
    expect(summarize(b, view)).toBe("Corne (crkbd) · 43 parts");
  });

  it("falls back to the kind of device, and says nothing it doesn't know", () => {
    expect(summarize(build({ spec: { device_class: "input_device" } as never, parts: [{ quantity: 3 }] as never }), emptyView())).toBe("Input device · 3 parts");
    expect(summarize(build({}), emptyView())).toBe("");
  });
});

const card = (id: string, over: Partial<LibraryCard> = {}): LibraryCard => ({ build_id: id, prompt: id, summary: "", status: "done", parts: 0, createdAt: 1, updatedAt: 1, thumb: null, mock: false, ...over });
const row = (id: string): StoredBuild => ({ build_id: id, prompt: id, device: null, created_at: "2026-10-01T00:00:00Z", status: "done", hero_url: null });

describe("deleting a build only hides it", () => {
  it("leaves hidden builds out of the list, here or on the engine", () => {
    const shown = mergeCards([card("b_local"), card("b_gone", { hidden: true })], [row("b_remote"), row("b_engine_hidden")], new Set(["b_engine_hidden"]));
    expect(shown.map((c) => c.build_id).sort()).toEqual(["b_local", "b_remote"]);
  });
  it("lists every hidden build once so it can be restored", () => {
    const hidden = hiddenCards([card("b_gone", { hidden: true }), card("b_both", { hidden: true })], [row("b_both"), row("b_engine_hidden")]);
    expect(hidden.map((c) => c.build_id).sort()).toEqual(["b_both", "b_engine_hidden", "b_gone"]);
    expect(hidden.every((c) => c.hidden)).toBe(true);
  });
});
