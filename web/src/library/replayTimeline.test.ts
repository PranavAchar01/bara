import { describe, expect, it } from "vitest";
import { frameAt, prepare, RUN_S, T } from "./replayTimeline";
import type { ReplayBuild } from "./replayData";
import landing from "./landingBuilds.json";

const builds = landing as ReplayBuild[];

describe("landing replay timeline", () => {
  it("bundles at least three devices", () => {
    expect(builds.length).toBeGreaterThanOrEqual(3);
  });

  it("builds from nothing: typing, then parts, board, traces, case", () => {
    const p = prepare(builds[0]);
    const start = frameAt(p, 0);
    expect(start.typed).toBe(0);
    expect(start.fps.every((f) => f.appear === 0)).toBe(true);
    expect(start.walls).toBe(0);
    const routed = frameAt(p, T.route[1]);
    expect(routed.board).toBe(1);
    expect(routed.traces.every((t) => t.drawn > 0.99)).toBe(true);
    const done = frameAt(p, T.done[0] + 0.5);
    expect(done.lid).toBe(1);
    expect(done.typed).toBe(builds[0].prompt.length);
    expect(T.out[1]).toBeLessThanOrEqual(RUN_S);
  });
});
