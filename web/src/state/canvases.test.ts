import { beforeEach, describe, expect, it } from "vitest";
import { loadFixtures } from "../spec/fixtures";
import type { ServerEnvelope } from "../spec/types";
import { createBuild, reduceAll } from "./reducer";
import { emptyView } from "./view";
import { useApp } from "./store";
import {
  addCanvas,
  addCompanionCanvas,
  applyStoredCanvases,
  canvasForOpening,
  canvasLabel,
  canvasOfBuild,
  canvasOfStart,
  canvasState,
  canvasStatus,
  closeCanvas,
  foldBuildEvent,
  parseCanvases,
  patchCanvas,
  renameCanvas,
  serializeCanvases,
  startedCanvas,
  switchCanvas,
} from "./canvases";

const fx = await loadFixtures();

/** The server events of a stream fixture that belong to its build, in order. */
function buildEvents(name: string): ServerEnvelope[] {
  const f = fx.streams.get(name);
  if (!f) throw new Error(`no fixture ${name}`);
  return f.steps.filter((s) => s.dir === "server" && s.msg.build_id && s.msg.seq > 0).map((s) => s.msg as ServerEnvelope);
}

const events = buildEvents("compose_wireless_split_oled");
const buildId = events[0].build_id as string;

beforeEach(() => {
  useApp.setState(useApp.getInitialState(), true);
});

describe("canvas tabs", () => {
  it("keeps each canvas's build, view, selection, camera preset, explode and toggles across a switch", () => {
    const build = reduceAll(createBuild(buildId, "a split keyboard"), events);
    const view = emptyView(5);
    useApp.setState({
      build,
      view,
      selection: build.parts[0]?.instance_id ?? null,
      preset: "top",
      explode: 0.7,
      toggles: { case: false, board: true, keycaps: false, labels: true },
      rightTab: "code",
    });
    const first = useApp.getState().activeCanvas;
    const second = addCanvas();
    let s = useApp.getState();
    expect(s.activeCanvas).toBe(second);
    expect(s.canvases.map((c) => c.id)).toEqual([first, second]);
    expect(s.build).toBeNull();
    expect(s.preset).toBe("scene");
    expect(s.explode).toBe(0);
    useApp.setState({ preset: "front", explode: 0.2 });

    const nonce = useApp.getState().cameraNonce;
    switchCanvas(first);
    s = useApp.getState();
    // the very same objects come back: nothing is rebuilt or re-run
    expect(s.build).toBe(build);
    expect(s.view).toBe(view);
    expect(s.selection).toBe(build.parts[0]?.instance_id ?? null);
    expect(s.preset).toBe("top");
    expect(s.explode).toBe(0.7);
    expect(s.toggles).toEqual({ case: false, board: true, keycaps: false, labels: true });
    expect(s.rightTab).toBe("code");
    expect(s.cameraNonce).toBe(nonce + 1);
    expect(s.canvasStash[second]).toMatchObject({ build: null, preset: "front", explode: 0.2 });
    expect(s.canvasStash[first]).toBeUndefined();
  });

  it("folds a background canvas's events into its stash, matching a straight replay", () => {
    const bg = useApp.getState().activeCanvas;
    patchCanvas(bg, startedCanvas({ msgId: "m1", prompt: "a split keyboard", ts: "2026-01-01T00:00:00Z", at: 0 }, buildId));
    const fg = addCanvas();
    for (const env of events) {
      const s = useApp.getState();
      const target = canvasOfBuild(s, env.build_id);
      expect(target).toBe(bg);
      patchCanvas(target as string, (c) => foldBuildEvent(c, env, 0));
    }
    const s = useApp.getState();
    expect(s.activeCanvas).toBe(fg);
    expect(s.build).toBeNull();
    const want = reduceAll(createBuild(buildId, "a split keyboard", "2026-01-01T00:00:00Z"), events);
    expect(s.canvasStash[bg].build).toEqual(want);
    expect(s.canvasStash[bg].view.done).not.toBeNull();
    expect(canvasStatus(s, bg)).toBe("done");
    expect(canvasStatus(s, fg)).toBe("empty");
  });

  it("finds the canvas that sent a build.start, even after switching away", () => {
    const a = useApp.getState().activeCanvas;
    useApp.setState({ pendingStart: { msgId: "m_a", prompt: "lamp", ts: "t", at: 0 } });
    expect(canvasStatus(useApp.getState(), a)).toBe("starting");
    const b = addCanvas();
    const s = useApp.getState();
    expect(canvasOfStart(s, "m_a")).toBe(a);
    expect(canvasOfStart(s, "m_b")).toBeNull();
    patchCanvas(a, startedCanvas(s.canvasStash[a].pendingStart!, "bld_lamp"));
    const after = useApp.getState();
    expect(after.activeCanvas).toBe(b);
    expect(after.canvasStash[a].build?.build_id).toBe("bld_lamp");
    expect(after.canvasStash[a].pendingStart).toBeNull();
    expect(canvasLabel(after.canvases[0], canvasState(after, a))).toBe("lamp");
  });

  it("closes to the right-hand neighbour, and to a fresh canvas after the last", () => {
    const a = useApp.getState().activeCanvas;
    const b = addCanvas();
    const c = addCanvas();
    switchCanvas(b);
    closeCanvas(b);
    expect(useApp.getState().activeCanvas).toBe(c);
    closeCanvas(c);
    expect(useApp.getState().activeCanvas).toBe(a);
    useApp.setState({ build: createBuild("bld_x", "x") });
    const closed = closeCanvas(a);
    const s = useApp.getState();
    expect(closed?.build?.build_id).toBe("bld_x");
    expect(s.canvases).toHaveLength(1);
    expect(s.build).toBeNull();
    expect(s.canvasStash).toEqual({});
  });

  it("opens a build on the canvas already showing it, else on the empty active one, else a new one", () => {
    const a = useApp.getState().activeCanvas;
    expect(canvasForOpening("bld_1")).toBe(a);
    useApp.setState({ build: createBuild("bld_1", "one") });
    const b = canvasForOpening("bld_2");
    expect(b).not.toBe(a);
    useApp.setState({ build: createBuild("bld_2", "two") });
    expect(canvasForOpening("bld_1")).toBe(a);
    expect(useApp.getState().activeCanvas).toBe(a);
    expect(useApp.getState().build?.build_id).toBe("bld_1");
  });

  it("stores ids, names and build ids, and reads them back as empty tabs to refetch", () => {
    useApp.setState({ build: createBuild("bld_1", "one") });
    const b = addCanvas();
    renameCanvas(b, "  Second  ");
    const stored = serializeCanvases(useApp.getState());
    expect(stored).toEqual({
      active: b,
      canvases: [
        { id: "c1", name: null, build_id: "bld_1", prompt: "one", companions: [] },
        { id: b, name: "Second", build_id: null, prompt: null, companions: [] },
      ],
    });
    const parsed = parseCanvases(JSON.stringify(stored));
    expect(parsed).toEqual(stored);

    useApp.setState(useApp.getInitialState(), true);
    applyStoredCanvases(parsed!);
    const s = useApp.getState();
    expect(s.activeCanvas).toBe(b);
    expect(s.canvases).toEqual([
      { id: "c1", name: null },
      { id: b, name: "Second" },
    ]);
    expect(s.canvasRestoring).toEqual(["c1"]);
    expect(canvasStatus(s, "c1")).toBe("restoring");
    expect(s.canvasStash.c1.build).toBeNull();
  });

  it("links a companion canvas both ways, and unlinks it when closed", () => {
    const a = useApp.getState().activeCanvas;
    const b = addCompanionCanvas();
    expect(useApp.getState().activeCanvas).toBe(b);
    expect(useApp.getState().companions).toEqual([a]);
    expect(canvasState(useApp.getState(), a)?.companions).toEqual([b]);
    const c = addCompanionCanvas();
    expect(useApp.getState().companions).toEqual([b, a]);
    expect(canvasState(useApp.getState(), a)?.companions).toEqual([b, c]);
    closeCanvas(b);
    expect(useApp.getState().companions).toEqual([a]);
    expect(canvasState(useApp.getState(), a)?.companions).toEqual([c]);
    const stored = parseCanvases(JSON.stringify(serializeCanvases(useApp.getState())))!;
    applyStoredCanvases(stored);
    expect(useApp.getState().companions).toEqual([a]);
    expect(canvasState(useApp.getState(), a)?.companions).toEqual([c]);
  });

  it("ignores a stored list it cannot read", () => {
    expect(parseCanvases(null)).toBeNull();
    expect(parseCanvases("{nope")).toBeNull();
    expect(parseCanvases(JSON.stringify({ canvases: [] }))).toBeNull();
    expect(parseCanvases(JSON.stringify({ active: "zz", canvases: [{ id: "c4", build_id: 3 }, { id: "bad" }] }))).toEqual({
      active: "c4",
      canvases: [{ id: "c4", name: null, build_id: null, prompt: null, companions: [] }],
    });
  });
});
