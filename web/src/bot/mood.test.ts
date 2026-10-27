import { describe, expect, it } from "vitest";
import { emoteFor, moodOf, speechFor, STAGE_ACTIVITY } from "./mood";

const base = { conn: "open" as const, typing: false, quietMs: 0 };
const ev = (type: string, payload: unknown) => ({ type, raw: JSON.stringify({ type, payload }) });

describe("bot mood", () => {
  it("acts out every build stage", () => {
    for (const [stage, activity] of Object.entries(STAGE_ACTIVITY)) {
      const m = moodOf({ ...base, buildStatus: "running", stage });
      expect(m.activity).toBe(activity);
      expect(m.mood).toBe(activity === "read" || activity === "search" ? "thinking" : "working");
    }
  });

  it("puts the connection and the user first", () => {
    expect(moodOf({ ...base, conn: "offline", buildStatus: "running", stage: "board" }).mood).toBe("offline");
    expect(moodOf({ ...base, conn: "reconnecting" }).mood).toBe("connecting");
    expect(moodOf({ ...base, typing: true, buildStatus: "done" }).mood).toBe("listening");
    expect(moodOf({ ...base, buildStatus: "awaiting_input" }).mood).toBe("asking");
  });

  it("is happy right after a build, then rests, then dozes", () => {
    expect(moodOf({ ...base, buildStatus: "done", sinceDoneMs: 1000 }).mood).toBe("happy");
    expect(moodOf({ ...base, buildStatus: "done", sinceDoneMs: 9000 }).mood).toBe("idle");
    expect(moodOf({ ...base, buildStatus: "done", sinceDoneMs: 90000, quietMs: 60000 }).mood).toBe("sleepy");
    expect(moodOf({ ...base, buildStatus: "failed" }).mood).toBe("sad");
  });

  it("reacts to events", () => {
    expect(emoteFor(ev("part.added", {}))).toBe("pop");
    expect(emoteFor(ev("build.done", {}))).toBe("delight");
    expect(emoteFor(ev("check.result", { results: [{ status: "pass" }] }))).toBeNull();
    expect(emoteFor(ev("check.result", { results: [{ status: "fail" }] }))).toBe("wince");
  });

  it("says one short line about an event", () => {
    expect(speechFor(ev("part.added", { part: { card: { display_name: "Tactile key switch" } } }))).toMatch(/clic/i);
    expect(speechFor(ev("part.added", { part: { label: "6mm knob" } }))).toMatch(/knob/i);
    expect(speechFor(ev("build.done", { summary: { instance_count: 76 } }))).toBe("There it is. All done!");
    expect(speechFor(ev("stage.started", { stage: "compose", label: "Choosing parts" }))).toBe("Shopping for parts!");
    // every line stays short enough to say in a breath
    for (const name of ["Rotary encoder", "Wireless controller board", "Battery", "USB-C receptacle", "Mystery widget"]) {
      const line = speechFor(ev("part.added", { part: { label: name } })) ?? "";
      expect(line.split(/\s+/).length).toBeLessThanOrEqual(10);
      expect(line).not.toMatch(/^Got /);
    }
    const long = speechFor(ev("stage.started", { label: "x".repeat(200) }));
    expect(long?.length).toBeLessThanOrEqual(60);
    expect(speechFor(ev("connection.added", {}))).toBeNull();
  });
});
