import { beforeEach, describe, expect, it, vi } from "vitest";

const startBuild = vi.fn();
vi.mock("../net/client", () => ({ startBuild: (p: string) => startBuild(p), deleteLibraryBuild: vi.fn(), fetchLibrary: vi.fn(async () => []), getRest: vi.fn() }));

import { canFinish, cardSubline, finishBuild, stateLabel } from "./finish";
import { useApp } from "../state/store";

describe("finish build", () => {
  beforeEach(() => {
    startBuild.mockClear();
    useApp.setState({ screen: "home", build: null, pendingStart: null });
  });

  it("labels a card by its real state", () => {
    expect(stateLabel("done")).toBe("Ready");
    expect(stateLabel("failed")).toBe("Needs finishing");
    expect(stateLabel("cancelled")).toBe("Needs finishing");
    expect(stateLabel("running")).toBe("In progress");
  });

  it("says checks passed only when every one did", () => {
    expect(cardSubline(30, true)).toBe("30 checks passed");
    expect(cardSubline(30, false)).toBe("Ready");
    expect(cardSubline(0, true)).toBe("Ready");
  });

  it("offers Finish only for a build that stopped short", () => {
    expect(canFinish("failed")).toBe(true);
    expect(canFinish("cancelled")).toBe(true);
    expect(canFinish("done")).toBe(false);
    expect(canFinish("running")).toBe(false);
  });

  it("runs the same request again and opens the workspace", () => {
    finishBuild("b1", "a split keyboard");
    expect(startBuild).toHaveBeenCalledWith("a split keyboard");
    expect(useApp.getState().screen).toBe("workspace");
  });
});
