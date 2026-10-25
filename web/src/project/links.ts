// A project is the devices in one scene (a canvas and its companions). Links connect them: a
// cable between two connectors, or a radio pairing. Pure functions over builds and catalog
// parts, so the panel, the 3D lines and the tests share one idea of what can connect to what.
import type { Build, BuildPart, Interface, Part } from "../spec/types";

export type Medium = "cable" | "wireless";

/** One interface on one part of one device that can reach another device. */
export interface DevicePort {
  canvasId: string;
  instanceId: string;
  interfaceId: string;
  type: string;
  role: string;
  medium: Medium;
  /** "USB-C on nice!nano v2" */
  label: string;
  partName: string;
  protocols: string[];
}

export interface PortKey {
  canvasId: string;
  instanceId: string;
  interfaceId: string;
}

export interface ProjectLink {
  link_id: string;
  a: PortKey;
  b: PortKey;
  medium: Medium;
  type: string;
  status: "ok" | "warning";
  note: string;
}

export const portKey = (p: PortKey) => `${p.canvasId}/${p.instanceId}/${p.interfaceId}`;
export const samePort = (x: PortKey, y: PortKey) => portKey(x) === portKey(y);

/** Interface types that leave the device on their own: plugs, jacks and radios. */
const OUTWARD = new Set(["usb", "jack", "qwiic", "radio"]);
/** Types that leave the device only through a connector part (a JST, a header, a terminal). */
const VIA_CONNECTOR = new Set(["power_in", "power_out", "i2c", "uart", "spi", "gpio", "battery"]);
const TYPE_LABEL: Record<string, string> = {
  usb: "USB",
  jack: "Jack",
  qwiic: "Qwiic",
  radio: "Radio",
  power_in: "Power in",
  power_out: "Power out",
  i2c: "I²C",
  uart: "UART",
  spi: "SPI",
  gpio: "GPIO",
  battery: "Battery",
};

function isConnectorPart(part: BuildPart): boolean {
  const t = `${part.part_id} ${part.card.primary_function ?? ""} ${part.card.display_name}`.toLowerCase();
  return /^conn:|connect\.|connector|jst|header|terminal|socket|jack|plug/.test(t);
}

function protocolsOf(itf: Interface): string[] {
  const p = itf.params ?? {};
  const raw = [p.protocol, p.protocols, p.standard, p.standards, p.radio].flat().filter((x): x is string => typeof x === "string");
  const words = raw.flatMap((s) => s.toLowerCase().split(/[\s,/+]+/));
  const label = `${itf.label ?? ""} ${itf.id}`.toLowerCase();
  const found = new Set(words.filter(Boolean));
  for (const k of ["ble", "bluetooth", "wifi", "wi-fi", "esp-now", "espnow", "zigbee", "thread", "lora", "nrf24"]) if (label.includes(k)) found.add(k);
  // one name per protocol
  const norm = (w: string) => (w === "bluetooth" ? "ble" : w === "wi-fi" ? "wifi" : w === "espnow" ? "esp-now" : w);
  return [...new Set([...found].map(norm))];
}

/** Ports of one device: its parts' outward interfaces (radios, plugs, connector pins). */
export function portsOf(canvasId: string, build: Build | null, parts: Record<string, Part | null | undefined>): DevicePort[] {
  if (!build) return [];
  const out: DevicePort[] = [];
  for (const inst of build.parts) {
    const part = parts[inst.part_id];
    if (!part?.interfaces) continue;
    const connector = isConnectorPart(inst);
    for (const itf of part.interfaces) {
      const type = String(itf.type);
      if (!OUTWARD.has(type) && !(connector && VIA_CONNECTOR.has(type))) continue;
      const name = inst.label ?? inst.card.display_name;
      const what = itf.label || TYPE_LABEL[type] || type;
      out.push({
        canvasId,
        instanceId: inst.instance_id,
        interfaceId: itf.id,
        type,
        role: String(itf.role),
        medium: type === "radio" ? "wireless" : "cable",
        label: `${what} on ${name}`,
        partName: name,
        protocols: type === "radio" ? protocolsOf(itf) : [],
      });
    }
  }
  return out;
}

export interface Fit {
  ok: boolean;
  status: "ok" | "warning";
  note: string;
}

/** Can these two ports be linked, and how well. */
export function compatibility(a: DevicePort, b: DevicePort): Fit {
  if (a.canvasId === b.canvasId) return { ok: false, status: "warning", note: "Both ports are on the same device" };
  if (a.medium !== b.medium) return { ok: false, status: "warning", note: "A radio pairs with a radio, a plug with a plug" };
  if (a.medium === "wireless") {
    const shared = a.protocols.filter((p) => b.protocols.includes(p));
    if (shared.length) return { ok: true, status: "ok", note: `Pairs over ${shared[0].toUpperCase()}` };
    if (!a.protocols.length || !b.protocols.length) return { ok: true, status: "warning", note: "Radios, but the protocol is not stated: check they match" };
    return { ok: false, status: "warning", note: `${a.protocols[0].toUpperCase()} and ${b.protocols[0].toUpperCase()} do not talk to each other` };
  }
  const pair = new Set([a.type, b.type]);
  if (pair.has("power_out") && pair.has("power_in")) return { ok: true, status: "ok", note: "Power from one feeds the other" };
  if (a.type.startsWith("power") || b.type.startsWith("power")) return { ok: false, status: "warning", note: "Power needs an output on one side and an input on the other" };
  if (a.type === b.type) return { ok: true, status: "ok", note: `${TYPE_LABEL[a.type] ?? a.type} cable` };
  if (pair.has("i2c") && pair.has("qwiic")) return { ok: true, status: "ok", note: "Qwiic carries I²C" };
  return { ok: false, status: "warning", note: `${TYPE_LABEL[a.type] ?? a.type} does not plug into ${TYPE_LABEL[b.type] ?? b.type}` };
}

const RANK: Record<string, number> = { radio: 0, usb: 1, qwiic: 2, jack: 3, i2c: 4, uart: 5, power_out: 6, power_in: 6 };

/** The best unlinked pair per device pair: radios first, then USB, Qwiic, jacks, pins. */
export function suggestLinks(ports: DevicePort[], links: ProjectLink[]): { a: DevicePort; b: DevicePort; fit: Fit }[] {
  const used = new Set(links.flatMap((l) => [portKey(l.a), portKey(l.b)]));
  const linkedPairs = new Set(links.map((l) => [l.a.canvasId, l.b.canvasId].sort().join("|")));
  const devices = [...new Set(ports.map((p) => p.canvasId))];
  const out: { a: DevicePort; b: DevicePort; fit: Fit }[] = [];
  for (let i = 0; i < devices.length; i++) {
    for (let j = i + 1; j < devices.length; j++) {
      if (linkedPairs.has([devices[i], devices[j]].sort().join("|"))) continue;
      const left = ports.filter((p) => p.canvasId === devices[i] && !used.has(portKey(p)));
      const right = ports.filter((p) => p.canvasId === devices[j] && !used.has(portKey(p)));
      let best: { a: DevicePort; b: DevicePort; fit: Fit; score: number } | null = null;
      for (const a of left)
        for (const b of right) {
          const fit = compatibility(a, b);
          if (!fit.ok) continue;
          const score = (RANK[a.type] ?? 9) + (fit.status === "ok" ? 0 : 5);
          if (!best || score < best.score) best = { a, b, fit, score };
        }
      if (best) out.push({ a: best.a, b: best.b, fit: best.fit });
    }
  }
  return out;
}

export function makeLink(a: DevicePort, b: DevicePort, fit: Fit): ProjectLink {
  const id = `l_${Math.random().toString(36).slice(2, 10)}`;
  const key = (p: DevicePort): PortKey => ({ canvasId: p.canvasId, instanceId: p.instanceId, interfaceId: p.interfaceId });
  return { link_id: id, a: key(a), b: key(b), medium: a.medium, type: a.type, status: fit.status, note: fit.note };
}

/** One CSV for the whole project: every device's parts, with the device named on each row. */
export function projectBomCsv(devices: { name: string; build: Build | null }[], links: ProjectLink[]): string {
  const esc = (v: unknown) => {
    const s = String(v ?? "");
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const rows: string[][] = [["device", "part", "part_id", "quantity", "licence"]];
  for (const d of devices) {
    for (const p of d.build?.parts ?? []) rows.push([d.name, p.label ?? p.card.display_name, p.part_id, String(p.quantity || 1), p.card.licence_spdx ?? ""]);
  }
  const cables = links.filter((l) => l.medium === "cable");
  for (const l of cables) rows.push(["(between devices)", `${l.note}`, `cable:${l.type}`, "1", ""]);
  return rows.map((r) => r.map(esc).join(",")).join("\n") + "\n";
}
