import { describe, expect, it } from "vitest";
import { createBuild, reduceBuild } from "../state/reducer";
import { loadFixtures } from "../spec/fixtures";
import type { Build, ClientEnvelope, Firmware, StreamFixture } from "../spec/types";
import { CONNECTION_SCOPED } from "../spec/types";
import { parseGadget, parseKconfig, parseMatrixTransform, parseQmkKeymap, parseZmkKeymap } from "./firmware";
import { loadDevice } from "./device";
import { SimMachine, legend } from "./machine";
import { codeToKeyName, keyInfo } from "./keys";

const fx = await loadFixtures();

function replay(name: string): Build {
  const f = fx.streams.get(name) as StreamFixture;
  let build: Build | null = null;
  let start: ClientEnvelope<"build.start"> | null = null;
  for (const step of f.steps) {
    if (step.dir === "client") {
      if (step.msg.type === "build.start") start = step.msg as ClientEnvelope<"build.start">;
      continue;
    }
    const env = step.msg;
    if (env.type === "ack" && start) {
      build = createBuild((env.payload as { build_id: string }).build_id, start.payload.prompt, start.ts);
      start = null;
      continue;
    }
    if (CONNECTION_SCOPED.has(env.type) || !build) continue;
    build = reduceBuild(build, env);
  }
  if (!build) throw new Error(`no build in ${name}`);
  return build;
}

/** A booted machine: past flashing, boot and the host link. */
function booted(build: Build, keymap?: { path: string; content: string }): SimMachine {
  const d = loadDevice(build, keymap);
  if (!d) throw new Error("no device");
  const m = new SimMachine(d);
  m.advance(5000);
  return m;
}

function keyAt(m: SimMachine, pos: number): string {
  const k = m.device.keys.find((x) => x.pos === pos);
  if (!k) throw new Error(`no key at ${pos}`);
  return k.id;
}

function tap(m: SimMachine, pos: number) {
  m.press(keyAt(m, pos));
  m.advance(30);
  m.release(keyAt(m, pos));
  m.advance(30);
}

describe("firmware parsing", () => {
  it("reads ZMK layers, layer defines and sensor bindings, and ignores combos", () => {
    const src = `
      #include <behaviors.dtsi>
      #define LOWER 1
      / {
        combos { compatible = "zmk,combos"; c { bindings = <&kp ESC>; key-positions = <0 1>; }; };
        keymap {
          compatible = "zmk,keymap";
          base { display-name = "Base"; bindings = <&kp Q &mo LOWER // comment
            &lt 1 SPACE &mt LSHFT A>; sensor-bindings = <&inc_dec_kp C_VOL_UP C_VOL_DN>; };
          lower_layer { bindings = <&trans &none &bt BT_SEL 2 &kp LS(N1)>; };
        };
      };`;
    const km = parseZmkKeymap(src);
    expect(km.layers.map((l) => l.name)).toEqual(["Base", "lower"]);
    expect(km.layers[0].bindings).toEqual([
      { kind: "kp", key: "Q" },
      { kind: "mo", layer: 1 },
      { kind: "lt", layer: 1, key: "SPACE" },
      { kind: "mt", mod: "LSHFT", key: "A" },
    ]);
    expect(km.layers[1].bindings[2]).toEqual({ kind: "bt", action: "BT_SEL", profile: 2 });
    expect(km.encoders).toEqual([{ cw: "C_VOL_UP", ccw: "C_VOL_DN" }]);
  });

  it("reads a QMK keymap.c with a layer enum", () => {
    const src = `
      enum layers { _BASE, _LOWER };
      const uint16_t PROGMEM keymaps[][MATRIX_ROWS][MATRIX_COLS] = {
        [_BASE] = LAYOUT_split_3x6_3(KC_A, MO(_LOWER), LT(_LOWER, KC_SPC), LSFT_T(KC_Z)),
        [_LOWER] = LAYOUT_split_3x6_3(KC_1, _______, XXXXXXX, S(KC_1)),
      };`;
    const km = parseQmkKeymap(src);
    expect(km.layers[0].bindings).toEqual([
      { kind: "kp", key: "A" },
      { kind: "mo", layer: 1 },
      { kind: "lt", layer: 1, key: "SPACE" },
      { kind: "mt", mod: "LSHFT", key: "Z" },
    ]);
    expect(km.layers[1].bindings).toEqual([{ kind: "kp", key: "N1" }, { kind: "trans" }, { kind: "none" }, { kind: "kp", key: "LS(N1)" }]);
  });

  it("reads Kconfig flags, the matrix transform and gadget peripherals", () => {
    expect(parseKconfig("CONFIG_ZMK_DISPLAY=y\n# x\nCONFIG_ZMK_IDLE_TIMEOUT=5000\n")).toEqual({ CONFIG_ZMK_DISPLAY: "y", CONFIG_ZMK_IDLE_TIMEOUT: "5000" });
    expect(parseMatrixTransform("map = <RC(0,0) RC(0,1)\n RC(1,0)>;")).toEqual([[0, 0], [0, 1], [1, 0]]);
    const fw = { files: [{ path: "bara.yaml", language: "yaml", content: "sensor:\n  - platform: bme280_i2c\n    update_interval: 5s\n" }], drivers: [] } as unknown as Firmware;
    expect(parseGadget(fw)).toMatchObject({ sensors: ["bme280"], updateMs: 5000 });
  });

  it("maps keys and modifier wrappers to what the host types", () => {
    expect(keyInfo("A")).toMatchObject({ char: "a", shifted: "A" });
    expect(keyInfo("LS(N1)").char).toBe("!");
    expect(keyInfo("LSHFT").modifier).toBe("shift");
    expect(codeToKeyName("KeyQ")).toBe("Q");
    expect(codeToKeyName("Digit4")).toBe("N4");
    expect(codeToKeyName("ShiftLeft")).toBe("LSHFT");
  });
});

describe("wireless split keyboard (compose_wireless_split_oled)", () => {
  const build = replay("compose_wireless_split_oled");

  it("loads the ZMK firmware onto 42 keys and falls back to the Corne default keymap for the stub file", () => {
    const d = loadDevice(build);
    expect(d?.framework).toBe("zmk");
    expect(d?.keys).toHaveLength(42);
    expect(d?.keymapSource).toBe("default");
    expect(d?.layers.map((l) => l.name)).toEqual(["Base", "Lower", "Raise"]);
    expect(d?.targets.map((t) => t.role)).toEqual(["central", "peripheral"]);
    expect(d?.displays).toHaveLength(2);
    // keymap positions run row by row across both halves: Tab top left, Bksp top right
    const first = d?.keys.find((k) => k.pos === 0);
    const twelfth = d?.keys.find((k) => k.pos === 11);
    expect(first?.side).toBe("left");
    expect(twelfth?.side).toBe("right");
    expect(d?.keys.filter((k) => k.thumb)).toHaveLength(6);
  });

  it("flashes both halves, boots, links the halves and connects to the host", () => {
    const d = loadDevice(build);
    if (!d) throw new Error("no device");
    const m = new SimMachine(d);
    expect(m.snapshot().phase).toBe("flashing");
    m.advance(100);
    expect(m.snapshot().flash?.target).toBe("Left half (central)");
    m.advance(5000);
    const s = m.snapshot();
    expect(s.phase).toBe("running");
    expect(s.hostConnected).toBe(true);
    expect(s.peripheralConnected).toBe(true);
    expect(s.console.some((l) => l.text.includes("Welcome to ZMK"))).toBe(true);
    expect(s.console.some((l) => l.text.includes("SDA P0.17"))).toBe(true);
  });

  it("types through the keymap, with shift and the lower and raise layers", () => {
    const m = booted(build);
    tap(m, 1); // Q
    tap(m, 2); // W
    m.press(keyAt(m, 24)); // LSHFT
    tap(m, 13); // A
    m.release(keyAt(m, 24));
    tap(m, 38); // SPACE (thumb)
    m.press(keyAt(m, 37)); // &mo 1
    expect(m.snapshot().topLayer).toBe(1);
    tap(m, 1); // N1 on lower
    m.release(keyAt(m, 37));
    m.press(keyAt(m, 40)); // &mo 2
    tap(m, 1); // EXCL on raise
    m.release(keyAt(m, 40));
    tap(m, 11); // BSPC
    const s = m.snapshot();
    expect(s.text).toBe("qwA 1");
    expect(s.topLayer).toBe(0);
    expect(s.hid.filter((r) => r.kind === "down").map((r) => r.key)).toContain("EXCL");
  });

  it("releases the binding it pressed even when the layer changed in between", () => {
    const m = booted(build);
    m.press(keyAt(m, 37)); // lower
    m.press(keyAt(m, 1)); // N1
    m.release(keyAt(m, 37));
    m.release(keyAt(m, 1));
    const ups = m.snapshot().hid.filter((r) => r.kind === "up").map((r) => r.key);
    expect(ups).toContain("N1");
    expect(ups).not.toContain("Q");
  });

  it("shows status on both OLEDs and blanks them when idle", () => {
    const m = booted(build);
    const d = m.device;
    const left = d.displays.find((x) => x.side === "left");
    const right = d.displays.find((x) => x.side === "right");
    m.press(keyAt(m, 37));
    let s = m.snapshot();
    expect(s.screens[left?.instanceId ?? ""]).toEqual(["BT1 OK  100%", "LOWER", expect.stringMatching(/^WPM \d+$/)]);
    expect(s.screens[right?.instanceId ?? ""]).toEqual(["BAT 96%", "LINKED"]);
    m.release(keyAt(m, 37));
    m.advance(31_000);
    s = m.snapshot();
    expect(s.phase).toBe("idle");
    expect(s.screens[left?.instanceId ?? ""]).toEqual([]);
    tap(m, 1);
    expect(m.snapshot().phase).toBe("running");
  });

  it("switches BLE profiles from the lower layer", () => {
    const m = booted(build);
    m.press(keyAt(m, 37));
    tap(m, 15); // &bt BT_SEL 1
    m.release(keyAt(m, 37));
    let s = m.snapshot();
    expect(s.profile).toBe(1);
    expect(s.hostConnected).toBe(false);
    tap(m, 1);
    expect(m.snapshot().text).toBe(""); // no host on profile 1
    m.press(keyAt(m, 37));
    tap(m, 14); // BT_SEL 0
    m.release(keyAt(m, 37));
    m.advance(2000);
    s = m.snapshot();
    expect(s.hostConnected).toBe(true);
  });

  it("runs a keymap the user loads in place of the build's, with hold-taps", () => {
    const keymap = `/ { keymap { compatible = "zmk,keymap";
      base { bindings = <&lt 1 SPACE &mt LSHFT A &kp B>; };
      num { bindings = <&kp N7 &trans &kp N8>; };
    }; };`;
    const m = booted(build, { path: "my.keymap", content: keymap });
    expect(m.device.keymapSource).toBe("firmware");
    expect(m.device.notes.some((n) => n.includes("binds 3 positions"))).toBe(true);
    tap(m, 0); // quick tap: SPACE
    m.press(keyAt(m, 0));
    m.advance(250); // past the tapping term: layer 1
    tap(m, 2); // N8
    m.release(keyAt(m, 0));
    m.press(keyAt(m, 1)); // &mt LSHFT A, interrupted: hold-preferred shift
    tap(m, 2);
    m.release(keyAt(m, 1));
    expect(m.snapshot().text).toBe(" 8B");
    expect(legend(m.bindingFor(0), m.device.layers.map((l) => l.name))).toBe("Space/num");
  });
});

describe("other firmware", () => {
  it("runs the QMK keyboard with its default keymap over USB", () => {
    const m = booted(replay("exact_keyboard"));
    expect(m.device.framework).toBe("qmk");
    expect(m.snapshot().hostConnected).toBe(true);
    tap(m, 1);
    expect(m.snapshot().text).toBe("q");
  });

  it("reads the BME280 on the Arduino gadget at the code's interval and draws it", () => {
    const build = replay("clarify_vague_gadget");
    const d = loadDevice(build);
    if (!d) throw new Error("no device");
    expect(d.kind).toBe("gadget");
    expect(d.updateMs).toBe(10_000);
    const m = new SimMachine(d);
    m.advance(3000);
    m.setEnvironment({ temperature: 30 });
    m.advance(10_000);
    const s = m.snapshot();
    expect(s.reading?.temperature).toBeCloseTo(30, 0);
    const oled = d.displays[0];
    expect(s.screens[oled.instanceId][0]).toMatch(/^30\.\d C$/);
  });
});

describe("programmatic API (for the bot)", () => {
  it("lists keys by legend, presses them and reports output changes", async () => {
    const api = await import("./api");
    const { useSimPanel } = await import("./simPanelStore");
    const m = booted(replay("compose_wireless_split_oled"));
    useSimPanel.setState({ open: true });
    api.setActiveMachine(m);
    const seen: string[] = [];
    const off = api.simSubscribe((s) => s && seen.push(s.text));
    expect(api.simIsOpen()).toBe(true);
    expect(api.simKeys()).toHaveLength(42);
    const q = api.simKeyFor("q");
    expect(q).toBeTruthy();
    api.simPress(q as string);
    api.simRelease(q as string);
    expect(api.simSnapshot()?.text).toBe("q");
    expect(seen).toContain("q");
    off();
    api.setActiveMachine(null);
    expect(api.simSnapshot()).toBeNull();
    expect(api.simKeys()).toEqual([]);
    useSimPanel.setState({ open: false });
  });
});

describe("real keyboard chords", () => {
  it("reaches keys on other layers through the layer key", async () => {
    const { chordFor } = await import("./input");
    const d = loadDevice(replay("compose_wireless_split_oled"));
    if (!d) throw new Error("no device");
    const byId = new Map(d.keys.map((k) => [k.id, k.pos]));
    expect(chordFor(d, "Q")?.map((id) => byId.get(id))).toEqual([1]);
    expect(chordFor(d, "N1")?.map((id) => byId.get(id))).toEqual([37, 1]);
    expect(chordFor(d, "RSHFT")?.map((id) => byId.get(id))).toEqual([24]);
  });
});
