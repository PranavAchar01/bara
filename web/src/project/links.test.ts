import { describe, expect, it } from "vitest";
import type { Build, BuildPart, Interface, Part } from "../spec/types";
import { compatibility, makeLink, portsOf, projectBomCsv, suggestLinks, type DevicePort } from "./links";

const itf = (id: string, type: string, role = "provides", params: Record<string, unknown> = {}, label?: string): Interface => ({ id, type, role, params, label });
const part = (part_id: string, interfaces: Interface[]): Part => ({ part_id, interfaces }) as unknown as Part;
const inst = (instance_id: string, part_id: string, display_name: string, primary_function = ""): BuildPart =>
  ({ instance_id, part_id, quantity: 1, card: { part_id, display_name, kind: "module", primary_function }, placement: { position_mm: [0, 0, 0], rotation_deg: [0, 0, 0] } }) as unknown as BuildPart;
const build = (parts: BuildPart[]): Build => ({ build_id: "b", parts }) as unknown as Build;

const PARTS: Record<string, Part> = {
  "mod:nice_nano": part("mod:nice_nano", [itf("usb", "usb", "provides", {}, "USB-C"), itf("ble", "radio", "provides", { protocols: ["BLE"] }), itf("i2c", "i2c")]),
  "mod:dongle": part("mod:dongle", [itf("usb", "usb", "requires", {}, "USB-C"), itf("radio", "radio", "provides", { protocol: "Bluetooth LE" })]),
  "mod:esp32": part("mod:esp32", [itf("wifi", "radio", "provides", { protocols: ["Wi-Fi"] })]),
  "conn:jst_sh": part("conn:jst_sh", [itf("i2c", "i2c"), itf("pwr", "power_out")]),
};

describe("project links", () => {
  it("finds a device's outward ports, not the pins inside it", () => {
    const ports = portsOf("kb", build([inst("u1", "mod:nice_nano", "nice!nano v2")]), PARTS);
    expect(ports.map((p) => p.type).sort()).toEqual(["radio", "usb"]);
    expect(ports.find((p) => p.type === "usb")?.label).toBe("USB-C on nice!nano v2");
    // the same I²C on a connector part does leave the device
    const viaJst = portsOf("sensor", build([inst("j1", "conn:jst_sh", "JST-SH 4-pin", "connect.qwiic")]), PARTS);
    expect(viaJst.map((p) => p.type).sort()).toEqual(["i2c", "power_out"]);
  });

  it("pairs radios on a shared protocol and plugs of the same kind", () => {
    const kb = portsOf("kb", build([inst("u1", "mod:nice_nano", "nice!nano v2")]), PARTS);
    const kbUsb = kb.find((p) => p.type === "usb") as DevicePort;
    const kbBle = kb.find((p) => p.type === "radio") as DevicePort;
    const dongle = portsOf("dg", build([inst("u2", "mod:dongle", "Dongle")]), PARTS);
    const wifi = portsOf("hub", build([inst("u3", "mod:esp32", "ESP32")]), PARTS)[0];
    const dBle = dongle.find((p) => p.type === "radio") as DevicePort;
    expect(compatibility(kbBle, dBle)).toMatchObject({ ok: true, status: "ok" });
    expect(compatibility(kbBle, wifi).ok).toBe(false);
    expect(compatibility(kbUsb, dongle.find((p) => p.type === "usb") as DevicePort).ok).toBe(true);
    expect(compatibility(kbUsb, dBle).ok).toBe(false);
    expect(compatibility(kbUsb, kbBle).ok).toBe(false); // same device
  });

  it("suggests the best link per device pair, radios first, and none once linked", () => {
    const ports = [...portsOf("kb", build([inst("u1", "mod:nice_nano", "nice!nano v2")]), PARTS), ...portsOf("dg", build([inst("u2", "mod:dongle", "Dongle")]), PARTS)];
    const s = suggestLinks(ports, []);
    expect(s).toHaveLength(1);
    expect(s[0].a.type).toBe("radio");
    const link = makeLink(s[0].a, s[0].b, s[0].fit);
    expect(suggestLinks(ports, [link])).toHaveLength(0);
  });

  it("writes one BOM for the whole project", () => {
    const csv = projectBomCsv(
      [
        { name: "Keyboard", build: build([inst("u1", "mod:nice_nano", "nice!nano v2")]) },
        { name: "Dongle", build: build([inst("u2", "mod:dongle", "Dongle")]) },
      ],
      [],
    );
    const lines = csv.trim().split("\n");
    expect(lines[0]).toBe("device,part,part_id,quantity,licence");
    expect(lines.slice(1).map((l) => l.split(",")[0])).toEqual(["Keyboard", "Dongle"]);
  });
});
