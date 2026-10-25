import { describe, expect, it } from "vitest";
import type { Build, BuildPart, Layout } from "../spec/types";
import { deriveInputMap, findPlus, labelledPlus, orderByPosition, screenUp } from "./inputMap";
import { createRuntime, press, release } from "./runtime";
import { inputForKey } from "./physical";

type V = [number, number, number];

function part(over: { id: string; fn: string; name?: string; label?: string; quantity?: number; layout?: string }): BuildPart {
  return {
    instance_id: over.id,
    part_id: over.id,
    label: over.label,
    quantity: over.quantity ?? 1,
    placement: {
      mode: over.layout ? "layout" : "single",
      position_mm: [0, 0, 0],
      rotation_deg: [0, 0, 0],
      layout_id: over.layout ?? null,
    },
    card: { display_name: over.name ?? over.id, primary_function: over.fn },
  } as unknown as BuildPart;
}

function build(parts: BuildPart[], extra: Record<string, unknown> = {}): Build {
  return { build_id: "b_test", status: "done", parts, ...extra } as unknown as Build;
}

const ROW: Layout = {
  layout_id: "L",
  pitch_x_mm: 19,
  pitch_y_mm: 19,
  keys: [0, 1, 2, 3].map((i) => ({ i, x_u: i, y_u: 0 })),
};

describe("orderByPosition", () => {
  it("lists the top row first, left to right inside a row", () => {
    const items = [
      { n: "c", pos: [10, 0, 0] as V },
      { n: "b", pos: [20, 10, 0] as V },
      { n: "a", pos: [0, 11, 0] as V },
      { n: "d", pos: [0, 0, 0] as V },
    ];
    expect(orderByPosition(items).map((i) => i.n)).toEqual(["a", "b", "d", "c"]);
  });
});

describe("findPlus", () => {
  it("finds a plus-shaped cluster", () => {
    const pts = [
      { x: 10, y: 20 },
      { x: 10, y: 0 },
      { x: 0, y: 10 },
      { x: 20, y: 10 },
    ];
    expect(findPlus(pts)).toEqual({ up: 0, down: 1, left: 2, right: 3 });
  });
  it("rejects a square of four", () => {
    expect(findPlus([{ x: 0, y: 0 }, { x: 10, y: 0 }, { x: 0, y: 10 }, { x: 10, y: 10 }])).toBeNull();
  });
  it("picks the leftmost plus when another sits beside it", () => {
    const pts = [
      { x: 60, y: 20 },
      { x: 60, y: 0 },
      { x: 50, y: 10 },
      { x: 70, y: 10 },
      { x: 10, y: 20 },
      { x: 10, y: 0 },
      { x: 0, y: 10 },
      { x: 20, y: 10 },
    ];
    const plus = findPlus(pts);
    expect(plus?.left).toBe(6);
    expect(plus?.right).toBe(7);
  });
});

describe("labelledPlus", () => {
  it("reads a D-pad part's four switches as a plus by angle, even with one arm pulled in", () => {
    // the board placer left the left arm near the middle: no clean plus, but the label says D-pad
    const pad = part({ id: "u_dpad", fn: "input.button", label: "D-pad direction switches", quantity: 4 });
    const ab = part({ id: "u_ab", fn: "input.button", label: "A and B action buttons", quantity: 2 });
    const raws = [
      { part: pad, pos: [-95, -8, 0] as V },
      { part: pad, pos: [-86, -17, 0] as V },
      { part: pad, pos: [-95, -26, 0] as V },
      { part: pad, pos: [-97, -18, 0] as V },
      { part: ab, pos: [92, -15, 0] as V },
      { part: ab, pos: [92, -3, 0] as V },
    ];
    expect(findPlus(raws.map((r) => ({ x: r.pos[0], y: r.pos[1] })))).toBeNull();
    expect(labelledPlus(raws)).toEqual({ up: 0, right: 1, down: 2, left: 3 });
    expect(labelledPlus(raws.slice(4))).toBeNull();
  });
});

describe("deriveInputMap: keyboard with a keymap", () => {
  const keymap = "bindings = < &kp Q &kp W &kp E &kp R &kp T &kp Y &kp U &kp BSPC >;";
  const wide: Layout = { ...ROW, keys: Array.from({ length: 8 }, (_, i) => ({ i, x_u: i, y_u: 0 })) };
  const b = build([part({ id: "sw", fn: "input.key", quantity: 8, layout: "L" })], {
    layouts: [wide],
    firmware: { framework: "zmk", files: [{ path: "config/k.keymap", content: keymap }] },
  });

  it("maps the Nth key to its &kp code and types", () => {
    const map = deriveInputMap(b);
    expect(map.mode).toBe("typing");
    expect(map.source).toBe("keymap");
    expect(map.inputs.map((i) => i.code)).toEqual(["Q", "W", "E", "R", "T", "Y", "U", "BSPC"]);
    const rt = createRuntime(map);
    for (const i of map.inputs.slice(0, 3)) {
      press(rt, i, map.inputs);
      release(rt, i);
    }
    expect(rt.terminal.text).toBe("qwe");
    press(rt, map.inputs[7], map.inputs);
    expect(rt.terminal.text).toBe("qw");
  });
  it("routes a physical key to the matching code", () => {
    const map = deriveInputMap(b);
    expect(inputForKey("KeyE", map.inputs)?.code).toBe("E");
    expect(inputForKey("Backspace", map.inputs)?.code).toBe("BSPC");
  });
});

describe("deriveInputMap: keys without a keymap", () => {
  it("falls back to position order names", () => {
    const map = deriveInputMap(build([part({ id: "sw", fn: "input.key", quantity: 4, layout: "L" })], { layouts: [ROW] }));
    expect(map.source).toBe("position");
    expect(map.inputs.map((i) => i.name)).toEqual(["K1", "K2", "K3", "K4"]);
    expect(map.mode).toBe("pad");
  });
});

describe("deriveInputMap: handheld from board footprints", () => {
  const rows: [string, number, number][] = [
    ["SW1", 20, 40],
    ["SW2", 20, 20],
    ["SW3", 10, 30],
    ["SW4", 30, 30],
    ["SW5", 80, 36],
    ["SW6", 90, 36],
    ["SW7", 80, 26],
    ["SW8", 90, 26],
  ];
  const footprints = rows.map(([ref, x, y]) => ({ ref, role: "button", center_mm: [x, y] }));
  const b = build(
    [
      part({ id: "btn", fn: "input.button", name: "Tactile switch", quantity: 8 }),
      part({ id: "rst", fn: "input.button", name: "Reset button", label: "reset" }),
      part({ id: "lcd", fn: "display.tft", name: "2.8 in TFT 320x240" }),
    ],
    { boards: [{ footprints, position_mm: [0, 0, 0], rotation_deg: [0, 0, 0] }] },
  );

  it("names the plus as a D-pad, the square as actions, and the reset by its label", () => {
    const map = deriveInputMap(b);
    expect(map.mode).toBe("game");
    expect(map.displays).toEqual(["lcd"]);
    const names = map.inputs.filter((i) => i.instanceId === "btn").map((i) => i.name);
    expect(names.slice(0, 4).sort()).toEqual(["DOWN", "LEFT", "RIGHT", "UP"]);
    expect(names.slice(4).sort()).toEqual(["A", "B", "X", "Y"]);
    expect(map.inputs.find((i) => i.name === "UP")?.pos[1]).toBe(40);
    expect(map.inputs.find((i) => i.instanceId === "rst")?.name).toBe("RESET");
  });

  it("an A press starts the game and a D-pad press steers it", () => {
    const map = deriveInputMap(b);
    const rt = createRuntime(map, 4 / 3, () => 0.5);
    const a = map.inputs.find((i) => i.name === "A");
    const up = map.inputs.find((i) => i.name === "UP");
    if (!a || !up) throw new Error("inputs missing");
    expect(rt.game.status).toBe("ready");
    press(rt, a, map.inputs);
    expect(rt.game.status).toBe("running");
    press(rt, up, map.inputs);
    expect(rt.events).toEqual(["A", "UP"]);
  });
});

describe("screenUp: which way a handheld stands", () => {
  const rows: [string, number, number][] = [
    ["SW1", 20, 40],
    ["SW2", 20, 20],
    ["SW3", 10, 30],
    ["SW4", 30, 30],
    ["SW5", 80, 36],
    ["SW6", 90, 26],
  ];
  const handheld = (turn: (x: number, y: number) => [number, number]) =>
    build([part({ id: "btn", fn: "input.button", name: "Tactile switch", quantity: 6 })], {
      boards: [{ footprints: rows.map(([ref, x, y]) => ({ ref, role: "button", center_mm: turn(x, y) })), position_mm: [0, 0, 0], rotation_deg: [0, 0, 0] }],
    });

  it("reads up from the D-pad on the left and the face buttons on the right", () => {
    expect(screenUp(handheld((x, y) => [x, y]))).toEqual([0, 1]);
  });

  it("follows a device laid a quarter turn round, and names the D-pad as the person sees it", () => {
    const b = handheld((x, y) => [-y, x]);
    expect(screenUp(b)).toEqual([-1, 0]);
    const up = deriveInputMap(b).inputs.find((i) => i.name === "UP");
    expect(up?.pos.slice(0, 2)).toEqual([-40, 20]);
  });

  it("follows a device laid upside down", () => {
    expect(screenUp(handheld((x, y) => [-x, -y]))).toEqual([0, -1]);
  });

  it("leaves keyboards to the long-axis rule", () => {
    expect(screenUp(build([part({ id: "sw", fn: "input.key", quantity: 4, layout: "L" })], { layouts: [ROW] }))).toBeNull();
  });
});

describe("deriveInputMap: nothing to press", () => {
  it("is empty for a build without inputs", () => {
    expect(deriveInputMap(build([part({ id: "x", fn: "mcu.rp2040" })])).inputs).toEqual([]);
    expect(deriveInputMap(null).inputs).toEqual([]);
  });
});
