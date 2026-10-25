import { describe, expect, it } from "vitest";
import { candidatesByKind, deviceKind, offlineGallery, pickGallery, scrubBrands } from "./gallery";
import type { StoredBuild } from "../net/client";

const sb = (id: string, device: string, prompt: string, over: Partial<StoredBuild> = {}): StoredBuild =>
  ({ build_id: id, device, prompt, created_at: id, status: "done", hero_url: null, ...over }) as StoredBuild;

describe("gallery", () => {
  it("never shows a product name", () => {
    expect(scrubBrands("a handheld game console like a Game Boy")).toBe("a handheld game console");
    expect(scrubBrands("Game Boy-style handheld game console")).toBe("handheld game console");
    expect(scrubBrands("stream deck macropad")).toBe("macropad");
  });

  it("treats small wording changes as one kind of device", () => {
    expect(deviceKind({ device: "wireless game controller", prompt: "" })).toBe("game controller");
    expect(deviceKind({ device: "wireless split keyboard with OLED", prompt: "" })).toBe("split keyboard");
  });

  it("keeps only finished builds, one group per kind", () => {
    const groups = candidatesByKind([sb("1", "rover", "a rover", { status: "failed" }), sb("2", "game controller", "x"), sb("3", "wireless game controller", "y")]);
    expect(groups.length).toBe(1);
    expect(groups[0].map((b) => b.build_id).sort()).toEqual(["2", "3"]);
  });

  it("skips a kind's builds whose checks failed and titles cards by device, not prompt", async () => {
    const builds = [sb("a", "Game Boy style handheld game console", "create a gameboy"), sb("b", "macropad", "a macropad")];
    const items = await pickGallery(builds, async (b) => ({ ok: b.build_id === "a", checks: 30, preview: null }));
    expect(items.map((i) => i.title)).toEqual(["Handheld game console"]);
    expect(items[0].prompt.toLowerCase()).not.toContain("gameboy");
  });

  it("bundled fallback leaves out the replay whose checks failed", () => {
    expect(offlineGallery().every((i) => i.preview?.failed === 0)).toBe(true);
  });
});
