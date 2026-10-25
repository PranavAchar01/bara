import { beforeEach, describe, expect, it } from "vitest";
import { loadFixtures } from "../spec/fixtures";
import type { Build, ServerEnvelope, ShellPalette } from "../spec/types";
import { createBuild, reduceAll } from "../state/reducer";
import { useApp } from "../state/store";
import { addCanvas, applyStoredCanvases, canvasState, parseCanvases, serializeCanvases, switchCanvas } from "../state/canvases";
import { addDeviceCanvas, deviceKindOf, kindOfBuild, sceneDevices, startStyleInherit, styleOf, takePendingPalette } from "./companion";

const fx = await loadFixtures();
const stream = fx.streams.get("compose_wireless_split_oled");
if (!stream) throw new Error("no fixture");
const events = stream.steps.filter((s) => s.dir === "server" && s.msg.build_id && s.msg.seq > 0).map((s) => s.msg as ServerEnvelope);
const buildId = events[0].build_id as string;

/** The fixture keyboard, built, with a known shell palette. */
function keyboard(): Build {
  const b = reduceAll(createBuild(buildId, "a wireless split keyboard with an OLED"), events);
  return {
    ...b,
    status: "done",
    scene: { ...(b.scene ?? { camera: { position_mm: [0, 0, 0], target_mm: [0, 0, 0] }, assembly_bbox_mm: { min: [0, 0, 0], max: [300, 120, 30] } }), finish: { palette: { body: "#1f2a44", trim: "#e8e1d0" } } },
  };
}

beforeEach(() => {
  useApp.setState(useApp.getInitialState(), true);
});

describe("device kinds", () => {
  it("names the head device of a line or prompt", () => {
    expect(deviceKindOf("a wireless mouse that pairs with the keyboard")).toBe("mouse");
    expect(deviceKindOf("A 75% keyboard")).toBe("keyboard");
    expect(deviceKindOf("game boy style handheld")).toBe("handheld");
    expect(deviceKindOf("a desk lamp")).toBeNull();
    expect(kindOfBuild(keyboard())).toBe("keyboard");
    expect(kindOfBuild(null, "mouse")).toBe("mouse");
    expect(kindOfBuild(null, "spaceship")).toBe("device");
  });
});

describe("the parent's look", () => {
  it("reads colours, connector and what the device is from its build", () => {
    const st = styleOf(keyboard());
    expect(st.kind).toBe("keyboard");
    expect(st.device).toBe("keyboard");
    expect(st.palette).toEqual({ body: "#1f2a44", trim: "#e8e1d0" });
    expect(st.connector).toMatch(/Bluetooth|USB/);
  });
});

describe("a new device canvas from a request", () => {
  it("opens a tab right after the parent, switched to, with both devices on it", () => {
    useApp.setState({ build: keyboard() });
    const parent = useApp.getState().activeCanvas;
    const later = addCanvas(); // a canvas after the parent, so the new tab must go between them
    switchCanvas(parent);
    expect(useApp.getState().build?.build_id).toBe(buildId);

    const id = addDeviceCanvas({ thing: "mouse", device_kind: "mouse", prompt: "a mouse that pairs with the keyboard" }, styleOf(keyboard()));
    const s = useApp.getState();
    expect(s.activeCanvas).toBe(id);
    expect(s.canvases.map((c) => c.id)).toEqual([parent, id, later]);
    expect(s.canvases[1]).toMatchObject({ id, name: "Mouse", kind: "mouse", pairsWith: parent });
    // both devices stand on the new canvas, and the parent's canvas shows the mouse too
    expect(s.companions).toEqual([parent]);
    expect(canvasState(s, parent)?.companions).toEqual([id]);
    expect(takePendingPalette(id)).toEqual({ body: "#1f2a44", trim: "#e8e1d0" });
  });

  it("gives the camera layout each device's kind and bounding box", () => {
    useApp.setState({ build: keyboard() });
    const parent = useApp.getState().activeCanvas;
    const id = addDeviceCanvas({ thing: "trackball", prompt: "a trackball" }, null);
    const devices = sceneDevices(useApp.getState());
    expect(devices.map((d) => [d.canvasId, d.kind, d.active, d.pairsWith])).toEqual([
      [parent, "keyboard", false, null],
      [id, "mouse", true, parent],
    ]);
    expect(devices[0].bbox_mm).not.toBeNull();
    expect(devices[1].bbox_mm).toBeNull(); // not built yet
  });

  it("keeps the kind and the pairing across a reload", () => {
    useApp.setState({ build: keyboard() });
    const parent = useApp.getState().activeCanvas;
    const id = addDeviceCanvas({ thing: "mouse", prompt: "a mouse" }, null);
    const stored = parseCanvases(JSON.stringify(serializeCanvases(useApp.getState())))!;
    useApp.setState(useApp.getInitialState(), true);
    applyStoredCanvases(stored);
    expect(useApp.getState().canvases.find((c) => c.id === id)).toMatchObject({ kind: "mouse", pairsWith: parent });
  });

  it("puts the parent's colours on the new device once, when it is built", () => {
    useApp.setState({ build: keyboard() });
    const got: Partial<ShellPalette>[] = [];
    const stop = startStyleInherit((p) => got.push(p));
    const id = addDeviceCanvas({ thing: "mouse", prompt: "a mouse" }, styleOf(keyboard()));
    useApp.setState({ build: { ...createBuild("bld_mouse", "a mouse"), status: "running" } });
    expect(got).toEqual([]);
    useApp.setState({ build: { ...createBuild("bld_mouse", "a mouse"), status: "done" } });
    useApp.setState({ build: { ...createBuild("bld_mouse", "a mouse"), status: "done", revision: 2 } });
    stop();
    expect(useApp.getState().activeCanvas).toBe(id);
    expect(got).toEqual([{ body: "#1f2a44", trim: "#e8e1d0" }]);
  });
});
