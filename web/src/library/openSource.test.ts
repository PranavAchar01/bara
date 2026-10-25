import { describe, expect, it } from "vitest";
import { filterBoards, firstSentence, packageName, scrubMakers, toPart, type OsBoard } from "./openSource";

const b = (o: Partial<OsBoard>): OsBoard => ({ id: "x", slug: "x", title: "T", owner: "o", repo: "r", category: "iot", stars: 1, license: "MIT", copyable: true, layers: 2, size_mm: null, parts: 1, url: null, commit: null, license_url: null, description: null, topics: null, thumb: true, ...o });

describe("open-source boards", () => {
  it("takes maker names out of shown text", () => {
    expect(scrubMakers("Cherry MX breakout board")).toBe("MX breakout board");
    expect(packageName("Panasonic_EVQPUL_EVQPUC")).toBe("EVQPUL EVQPUC");
    expect(packageName("Package_SO:SOIC-16_3.9x9.9mm_P1.27mm")).toBe("SOIC-16 3.9x9.9mm P1.27mm");
  });
  it("describes a part in one clean line", () => {
    expect(firstSentence("75V 0.15A Fast Switching Diode, SOD-123. More text.")).toBe("75V 0.15A Fast Switching Diode, SOD-123.");
    const p = toPart(["D1", "", "ComboDiode", "", "top", [1, 2], 0]);
    expect(p.what).toBe("A ComboDiode part.");
  });
  it("filters by category, licence switch and search, and sorts", () => {
    const list = [b({ id: "a", title: "A", stars: 5, parts: 9 }), b({ id: "b", title: "B", stars: 9, parts: 2, copyable: false }), b({ id: "c", title: "C", category: "audio", stars: 7, parts: 3 })];
    expect(filterBoards(list, { q: "", category: null, copyableOnly: false, sort: "popular" }).map((x) => x.id)).toEqual(["b", "c", "a"]);
    expect(filterBoards(list, { q: "", category: null, copyableOnly: true, sort: "parts" }).map((x) => x.id)).toEqual(["a", "c"]);
    expect(filterBoards(list, { q: "c", category: "audio", copyableOnly: false, sort: "popular" }).map((x) => x.id)).toEqual(["c"]);
  });
});
