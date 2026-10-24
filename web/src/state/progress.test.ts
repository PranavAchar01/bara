import { describe, expect, it } from "vitest";
import { buildProgress, fmtDuration, fmtLeft, TYPICAL_MS } from "./progress";
import { emptyStages } from "./view";

describe("buildProgress", () => {
  it("starts near zero with the typical build as time left", () => {
    const p = buildProgress(emptyStages(), 0, 1000);
    expect(p.fraction).toBe(0);
    expect(p.leftMs).toBe(TYPICAL_MS - 1000);
  });

  it("counts finished stages and paces time left on the build's own speed", () => {
    const stages = emptyStages();
    for (const id of ["classify", "reuse", "compose", "place", "enclose"]) stages[id] = { id, status: "ok" };
    stages.board = { id: "board", status: "active", startedAt: 100_000, fraction: 0.5 };
    const p = buildProgress(stages, 0, 200_000);
    expect(p.fraction).toBeCloseTo(0.675, 3);
    expect(p.leftMs).toBeCloseTo((200_000 * 0.325) / 0.675, 0);
  });

  it("never reads a slow stage as finished", () => {
    const stages = emptyStages();
    stages.classify = { id: "classify", status: "active", startedAt: 0 };
    expect(buildProgress(stages, 0, 10 * TYPICAL_MS).fraction).toBeCloseTo(0.045, 3);
  });

  it("formats time left and duration", () => {
    expect(fmtLeft(30_000)).toBe("under a minute left");
    expect(fmtLeft(4 * 60_000)).toBe("about 4 min left");
    expect(fmtDuration(372_000)).toBe("6m 12s");
  });
});
