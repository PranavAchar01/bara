// The simulated device at run time. Time only moves through advance(ms), so tests drive it
// deterministically and the view drives it from the frame clock.
//
// Keyboards follow ZMK's documented behaviour: a key resolves through the active layers from the
// top down (&trans falls through), the binding found on press is the one released, &mo holds a
// layer, &lt/&mt are tap on release before the 200 ms tapping term and hold after it (&mt is
// hold-preferred: another key going down makes it a hold), the central half owns the BLE link,
// the display blanks after CONFIG_ZMK_IDLE_TIMEOUT (30 s) and the board sleeps after
// CONFIG_ZMK_IDLE_SLEEP_TIMEOUT (15 min) when CONFIG_ZMK_SLEEP is on.
import type { Binding } from "./firmware";
import type { SimDevice } from "./device";
import { keyInfo } from "./keys";

export type Phase = "flashing" | "booting" | "running" | "idle" | "asleep";

export interface ConsoleLine {
  id: number;
  t: number;
  source: string;
  level: "inf" | "dbg" | "wrn" | "sim";
  text: string;
}

export interface HidReport {
  id: number;
  t: number;
  kind: "down" | "up" | "consumer";
  key: string;
  mods: string[];
}

export interface SensorReading {
  temperature: number;
  humidity: number;
  pressure: number;
}

export interface SimSnapshot {
  t: number;
  phase: Phase;
  flash: { target: string; fraction: number } | null;
  layers: number[];
  topLayer: number;
  pressed: string[];
  mods: string[];
  text: string;
  hid: HidReport[];
  console: ConsoleLine[];
  profile: number;
  hostConnected: boolean;
  peripheralConnected: boolean;
  battery: Record<string, number>;
  wpm: number;
  /** What the environment is (the user's sliders) and what the firmware last read. */
  environment: SensorReading;
  reading: SensorReading | null;
  encoderValue: number;
  /** Lines on each display, by instance id; [] when the display is blank. */
  screens: Record<string, string[]>;
  revision: number;
}

const TAPPING_TERM_MS = 200;
const FLASH_MS_PER_TARGET = 700;
const BOOT_MS = 500;
const HOST_CONNECT_MS = 1200;
const SPLIT_CONNECT_MS = 800;
const LOG_CAP = 400;
const HID_CAP = 60;

interface Held {
  binding: Binding;
  layer: number;
  at: number;
  /** hold-tap: decided yet, and which way */
  decided?: "tap" | "hold";
}

interface Timer {
  at: number;
  run: () => void;
}

export class SimMachine {
  readonly device: SimDevice;
  private t = 0;
  private phase: Phase = "flashing";
  private flash: SimSnapshot["flash"] = null;
  private momentary: number[] = [];
  private toggled = new Set<number>();
  private base = 0;
  private held = new Map<string, Held>();
  private mods = new Map<string, number>();
  private text = "";
  private hid: HidReport[] = [];
  private log: ConsoleLine[] = [];
  private profile = 0;
  private hostConnected = false;
  private peripheralConnected = false;
  private battery: Record<string, number> = {};
  private pressTimes: number[] = [];
  private lastActivity = 0;
  private timers: Timer[] = [];
  private seq = 0;
  private revision = 0;
  private environment: SensorReading = { temperature: 21.4, humidity: 45, pressure: 1013.2 };
  private reading: SensorReading | null = null;
  private encoderValue = 0;
  private listeners = new Set<() => void>();
  private snap: SimSnapshot | null = null;

  constructor(device: SimDevice) {
    this.device = device;
    for (const tg of device.targets) this.battery[tg.side] = tg.side === "right" ? 96 : 100;
    if (!device.targets.length) this.battery.none = 100;
    this.flashAll();
  }

  // --- public API -------------------------------------------------------------------------

  subscribe = (fn: () => void): (() => void) => {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  };

  snapshot = (): SimSnapshot => {
    if (!this.snap) this.snap = this.build();
    return this.snap;
  };

  advance(ms: number): void {
    const end = this.t + Math.max(0, ms);
    for (;;) {
      this.timers.sort((a, b) => a.at - b.at);
      const next = this.timers[0];
      if (!next || next.at > end) break;
      this.timers.shift();
      this.t = Math.max(this.t, next.at);
      next.run();
    }
    const before = this.phase;
    this.t = end;
    this.checkIdle();
    // the clock itself is not a change worth a re-render; timers that show something call changed()
    if (before !== this.phase) this.changed();
  }

  press(keyId: string): void {
    const key = this.device.keys.find((k) => k.id === keyId);
    if (!key || this.held.has(keyId)) return;
    if (!this.wake()) return;
    // hold-preferred mod-taps that are still undecided become holds when another key goes down
    for (const [id, h] of this.held) {
      if (h.binding.kind === "mt" && !h.decided) this.decideHold(id, h);
    }
    const { binding, layer } = this.resolve(key.pos);
    const h: Held = { binding, layer, at: this.t };
    this.held.set(keyId, h);
    this.pressTimes.push(this.t);
    this.emitLog("zmk", "dbg", `position ${key.pos} pressed, layer ${layer} binding ${describe(binding)}`);
    switch (binding.kind) {
      case "kp":
        this.keyDown(binding.key);
        break;
      case "mo":
        this.momentary.push(binding.layer);
        this.layerChanged();
        break;
      case "to":
        this.base = binding.layer;
        this.toggled.clear();
        this.layerChanged();
        break;
      case "tog":
        if (this.toggled.has(binding.layer)) this.toggled.delete(binding.layer);
        else this.toggled.add(binding.layer);
        this.layerChanged();
        break;
      case "lt":
      case "mt":
        this.timers.push({ at: this.t + TAPPING_TERM_MS, run: () => this.held.get(keyId) === h && !h.decided && this.decideHold(keyId, h) });
        break;
      case "bt":
        this.bluetooth(binding);
        break;
      case "out":
        this.emitLog("zmk", "inf", `output selection ${binding.action}`);
        break;
      case "none":
      case "trans":
        break;
      case "other":
        this.emitLog("zmk", "wrn", `behaviour ${binding.raw} is not simulated`);
        break;
    }
    this.changed();
  }

  release(keyId: string): void {
    const h = this.held.get(keyId);
    if (!h) return;
    this.held.delete(keyId);
    const b = h.binding;
    if (b.kind === "kp") this.keyUp(b.key);
    else if (b.kind === "mo") {
      const i = this.momentary.lastIndexOf(b.layer);
      if (i >= 0) this.momentary.splice(i, 1);
      this.layerChanged();
    } else if (b.kind === "lt" || b.kind === "mt") {
      if (h.decided === "hold") {
        if (b.kind === "lt") {
          const i = this.momentary.lastIndexOf(b.layer);
          if (i >= 0) this.momentary.splice(i, 1);
          this.layerChanged();
        } else this.keyUp(b.mod);
      } else {
        // released inside the tapping term: a tap
        this.keyDown(b.key);
        this.keyUp(b.key);
      }
    }
    this.changed();
  }

  releaseAll(): void {
    for (const id of [...this.held.keys()]) this.release(id);
  }

  turnEncoder(index: number, dir: 1 | -1): void {
    if (!this.wake()) return;
    const enc = this.device.encoders[index];
    if (!enc) return;
    this.encoderValue += dir;
    if (this.device.kind === "keyboard") {
      const key = dir > 0 ? enc.cw : enc.ccw;
      this.report("consumer", key);
      this.emitLog("zmk", "dbg", `sensor ${index} rotated ${dir > 0 ? "clockwise" : "anticlockwise"}: ${key}`);
    } else {
      this.emitLog(this.device.framework === "esphome" ? "[D][rotary_encoder]" : "loop", "dbg", `encoder value ${this.encoderValue}`);
    }
    this.changed();
  }

  setEnvironment(patch: Partial<SensorReading>): void {
    this.environment = { ...this.environment, ...patch };
    this.changed();
  }

  /** Re-flash: everything back to power-on. */
  reset(): void {
    this.timers = [];
    this.held.clear();
    this.mods.clear();
    this.momentary = [];
    this.toggled.clear();
    this.base = 0;
    this.hostConnected = false;
    this.peripheralConnected = false;
    this.reading = null;
    this.emitLog("sim", "sim", "reset");
    this.flashAll();
  }

  clearOutput(): void {
    this.text = "";
    this.hid = [];
    this.changed();
  }

  /** Binding a key does on the current layers (for its legend). */
  bindingFor(pos: number): Binding {
    return this.resolve(pos).binding;
  }

  activeLayers(): number[] {
    const set = new Set<number>([this.base, ...this.toggled, ...this.momentary]);
    return [...set].filter((l) => l < this.device.layers.length).sort((a, b) => a - b);
  }

  // --- internals --------------------------------------------------------------------------

  private changed(): void {
    this.snap = null;
    this.revision++;
    for (const fn of this.listeners) fn();
  }

  private emitLog(source: string, level: ConsoleLine["level"], text: string): void {
    this.log.push({ id: ++this.seq, t: this.t, source, level, text });
    if (this.log.length > LOG_CAP) this.log.splice(0, this.log.length - LOG_CAP);
  }

  private at(delay: number, run: () => void): void {
    this.timers.push({ at: this.t + delay, run });
  }

  private flashAll(): void {
    const d = this.device;
    this.phase = "flashing";
    this.lastActivity = this.t;
    for (const n of d.notes) this.emitLog("sim", "sim", n);
    const targets = d.targets.length ? d.targets : [{ targetId: "main", label: "Main", side: "none", binary: null }];
    targets.forEach((tg, i) => {
      const name = tg.binary?.name ?? `${tg.targetId} (${d.framework} source)`;
      this.at(i * FLASH_MS_PER_TARGET, () => {
        this.flash = { target: tg.label, fraction: 0 };
        this.emitLog("sim", "sim", `loading ${name} onto ${tg.label}${tg.binary?.bytes ? `, ${Math.round(tg.binary.bytes / 1024)} KB` : ""}`);
        this.changed();
      });
      for (let s = 1; s <= 4; s++)
        this.at(i * FLASH_MS_PER_TARGET + (s * FLASH_MS_PER_TARGET) / 4, () => {
          this.flash = { target: tg.label, fraction: s / 4 };
          this.changed();
        });
    });
    this.at(targets.length * FLASH_MS_PER_TARGET, () => {
      this.flash = null;
      this.phase = "booting";
      this.bootLog();
      this.changed();
    });
    this.at(targets.length * FLASH_MS_PER_TARGET + BOOT_MS, () => {
      this.phase = "running";
      this.lastActivity = this.t;
      this.startRunning();
      this.changed();
    });
    this.changed();
  }

  private bootLog(): void {
    const d = this.device;
    if (d.framework === "zmk") {
      for (const tg of d.targets.length ? d.targets : [{ label: "Main", side: "none", role: "single" }]) {
        this.emitLog(tg.label, "inf", "*** Booting Zephyr OS ***");
        this.emitLog(tg.label, "inf", `zmk: Welcome to ZMK! (${tg.role === "peripheral" ? "split peripheral" : tg.role === "central" ? "split central" : "standalone"})`);
      }
      for (const disp of d.displays) {
        const sda = d.pins.find((p) => p.instanceId === disp.instanceId && p.signal === "SDA");
        const scl = d.pins.find((p) => p.instanceId === disp.instanceId && p.signal === "SCL");
        if (this.flag("CONFIG_ZMK_DISPLAY"))
          this.emitLog("zmk", "inf", `display: ssd1306 ${disp.width}x${disp.height} at 0x3c${sda ? ` (SDA ${sda.mcuPin}, SCL ${scl?.mcuPin ?? "?"})` : ""}`);
      }
      if (!this.flag("CONFIG_ZMK_DISPLAY") && d.displays.length) this.emitLog("zmk", "wrn", "CONFIG_ZMK_DISPLAY is off: the OLED stays dark");
      this.emitLog("zmk", "inf", `keymap: ${d.layers.length} layer${d.layers.length === 1 ? "" : "s"} (${d.layers.map((l) => l.name).join(", ")}), ${d.keys.length} keys`);
    } else if (d.framework === "qmk") {
      this.emitLog("qmk", "inf", `QMK firmware, ${d.keys.length} keys, ${d.layers.length} layers`);
    } else if (d.framework === "esphome") {
      this.emitLog("[I][app]", "inf", "Running through setup()...");
      for (const s of d.sensors) this.emitLog(`[C][${s.kind}]`, "inf", `${s.label} found at 0x76`);
      for (const disp of d.displays) this.emitLog("[C][ssd1306]", "inf", `${disp.label}: ${disp.width}x${disp.height}`);
    } else {
      this.emitLog("serial", "inf", "setup(): Wire.begin()");
      for (const s of d.sensors) this.emitLog("serial", "inf", `${s.kind}.begin(0x76) ok`);
      for (const disp of d.displays) this.emitLog("serial", "inf", `display.begin(0x3C) ok (${disp.width}x${disp.height})`);
    }
  }

  private startRunning(): void {
    const d = this.device;
    if (d.kind === "keyboard") {
      const split = d.targets.length > 1;
      if (split) this.at(SPLIT_CONNECT_MS, () => {
        this.peripheralConnected = true;
        this.emitLog("zmk", "inf", "split: peripheral connected to central");
        this.changed();
      });
      if (this.ble()) {
        this.emitLog("zmk", "inf", `ble: advertising on profile ${this.profile}`);
        this.at(HOST_CONNECT_MS, () => {
          this.hostConnected = true;
          this.emitLog("zmk", "inf", `ble: connected to host on profile ${this.profile}`);
          this.changed();
        });
      } else {
        this.hostConnected = true;
        this.emitLog(d.framework, "inf", "usb: enumerated as HID keyboard");
      }
    } else {
      this.read();
    }
  }

  private read(): void {
    if (this.phase !== "running" && this.phase !== "idle") return;
    const d = this.device;
    if (d.sensors.length) {
      // a real sensor reads with a little noise
      const n = (x: number, a: number) => Math.round((x + Math.sin(this.t / 997 + a) * 0.05) * 10) / 10;
      this.reading = { temperature: n(this.environment.temperature, 1), humidity: n(this.environment.humidity, 2), pressure: n(this.environment.pressure, 3) };
      const r = this.reading;
      if (d.framework === "esphome") {
        this.emitLog("[D][sensor]", "dbg", `'Temperature': Sending state ${r.temperature.toFixed(5)} °C`);
        this.emitLog("[D][sensor]", "dbg", `'Humidity': Sending state ${r.humidity.toFixed(5)} %`);
        this.emitLog("[D][sensor]", "dbg", `'Pressure': Sending state ${r.pressure.toFixed(5)} hPa`);
      } else this.emitLog("serial", "inf", `T=${r.temperature.toFixed(1)}C H=${r.humidity.toFixed(1)}% P=${r.pressure.toFixed(1)}hPa`);
    } else this.emitLog(d.framework === "esphome" ? "[D][app]" : "serial", "dbg", "loop()");
    this.at(d.updateMs, () => this.read());
    this.changed();
  }

  private flag(name: string): boolean {
    return this.device.config[name] === "y";
  }

  private ble(): boolean {
    // ZMK turns BLE on by default for wireless boards (nice!nano); the template only writes it when asked
    return this.flag("CONFIG_ZMK_BLE") || (this.device.framework === "zmk" && this.device.config.CONFIG_ZMK_BLE !== "n");
  }

  private wake(): boolean {
    if (this.phase === "flashing" || this.phase === "booting") return false;
    this.lastActivity = this.t;
    if (this.phase === "idle" || this.phase === "asleep") {
      const was = this.phase;
      this.phase = "running";
      this.emitLog("zmk", "inf", was === "asleep" ? "woke from deep sleep" : "activity: display on");
      if (was === "asleep") {
        this.hostConnected = false;
        this.peripheralConnected = false;
        this.startRunning();
      }
      this.changed();
    }
    return true;
  }

  private checkIdle(): void {
    if (this.device.kind !== "keyboard" || this.held.size > 0) return;
    const idleFor = this.t - this.lastActivity;
    const idleMs = Number(this.device.config.CONFIG_ZMK_IDLE_TIMEOUT ?? 30_000);
    const sleepMs = Number(this.device.config.CONFIG_ZMK_IDLE_SLEEP_TIMEOUT ?? 900_000);
    if (this.phase === "running" && idleFor >= idleMs) {
      this.phase = "idle";
      this.emitLog("zmk", "inf", `idle for ${Math.round(idleMs / 1000)} s: display off`);
    }
    if (this.phase === "idle" && this.flag("CONFIG_ZMK_SLEEP") && idleFor >= sleepMs) {
      this.phase = "asleep";
      this.emitLog("zmk", "inf", "deep sleep (CONFIG_ZMK_SLEEP); any key wakes the board");
    }
  }

  private resolve(pos: number): { binding: Binding; layer: number } {
    const active = this.activeLayers();
    for (let i = active.length - 1; i >= 0; i--) {
      const b = this.device.layers[active[i]]?.bindings[pos];
      if (!b) continue;
      if (b.kind !== "trans") return { binding: b, layer: active[i] };
    }
    return { binding: { kind: "none" }, layer: 0 };
  }

  private decideHold(keyId: string, h: Held): void {
    h.decided = "hold";
    const b = h.binding;
    if (b.kind === "lt") {
      this.momentary.push(b.layer);
      this.layerChanged();
    } else if (b.kind === "mt") this.keyDown(b.mod);
    this.emitLog("zmk", "dbg", `${keyId} held past the tapping term: ${describe(b)} hold`);
    this.changed();
  }

  private layerChanged(): void {
    const top = this.activeLayers().at(-1) ?? 0;
    this.emitLog("zmk", "dbg", `layer ${top} (${this.device.layers[top]?.name ?? "?"}) active`);
  }

  private bluetooth(b: Extract<Binding, { kind: "bt" }>): void {
    if (b.action === "BT_SEL" && b.profile !== undefined) {
      this.profile = b.profile;
      this.hostConnected = false;
      this.emitLog("zmk", "inf", `ble: selected profile ${b.profile}, advertising`);
      // profile 0 is the paired host in the simulation; others wait for a pairing that never comes
      if (b.profile === 0) this.at(HOST_CONNECT_MS, () => {
        this.hostConnected = this.profile === 0;
        if (this.hostConnected) this.emitLog("zmk", "inf", "ble: connected to host on profile 0");
        this.changed();
      });
    } else if (b.action === "BT_CLR") {
      this.hostConnected = false;
      this.emitLog("zmk", "inf", `ble: cleared bond on profile ${this.profile}`);
    } else this.emitLog("zmk", "inf", `ble: ${b.action}`);
  }

  private activeMods(): string[] {
    return [...this.mods.entries()].filter(([, n]) => n > 0).map(([m]) => m);
  }

  private report(kind: HidReport["kind"], key: string): void {
    this.hid.push({ id: ++this.seq, t: this.t, kind, key, mods: this.activeMods() });
    if (this.hid.length > HID_CAP) this.hid.splice(0, this.hid.length - HID_CAP);
  }

  private keyDown(key: string): void {
    const info = keyInfo(key);
    if (info.modifier) {
      this.mods.set(key, (this.mods.get(key) ?? 0) + 1);
      this.report("down", key);
      return;
    }
    this.report("down", key);
    if (!this.hostConnected) return;
    const mods = this.activeMods().map((m) => keyInfo(m).modifier);
    if (mods.includes("ctrl") || mods.includes("gui") || mods.includes("alt")) return;
    const shift = mods.includes("shift") || /^LS\(|^RS\(/.test(key);
    const ch = shift ? (info.shifted ?? info.char) : info.char;
    if (ch === "\b") this.text = this.text.slice(0, -1);
    else if (ch) this.text = (this.text + ch).slice(-4000);
  }

  private keyUp(key: string): void {
    const info = keyInfo(key);
    if (info.modifier) {
      const n = (this.mods.get(key) ?? 1) - 1;
      if (n <= 0) this.mods.delete(key);
      else this.mods.set(key, n);
    }
    this.report("up", key);
  }

  private wpm(): number {
    // ZMK's WPM widget: key presses over the last minute, five per word, refreshed per second
    const since = this.t - 60_000;
    this.pressTimes = this.pressTimes.filter((x) => x >= since);
    const window = Math.min(60_000, Math.max(5_000, this.t));
    return Math.round(this.pressTimes.length / 5 / (window / 60_000));
  }

  private screens(): Record<string, string[]> {
    const d = this.device;
    const out: Record<string, string[]> = {};
    for (const disp of d.displays) {
      const on = this.phase === "running" && (d.framework !== "zmk" || this.flag("CONFIG_ZMK_DISPLAY"));
      if (!on) {
        out[disp.instanceId] = [];
        continue;
      }
      if (d.kind === "gadget") {
        const r = this.reading;
        out[disp.instanceId] = r
          ? [`${r.temperature.toFixed(1)} C`, `${r.humidity.toFixed(0)} %RH`, `${r.pressure.toFixed(0)} hPa`]
          : ["reading..."];
        continue;
      }
      const target = d.targets.find((t) => t.side === disp.side) ?? d.targets[0];
      const bat = `${this.battery[disp.side] ?? this.battery[target?.side ?? "none"] ?? 100}%`;
      if (target?.role === "peripheral") {
        out[disp.instanceId] = [`BAT ${bat}`, this.peripheralConnected ? "LINKED" : "NO LINK"];
        continue;
      }
      const top = this.activeLayers().at(-1) ?? 0;
      const link = this.ble() ? `BT${this.profile + 1} ${this.hostConnected ? "OK" : "..."}` : "USB";
      out[disp.instanceId] = [`${link}  ${bat}`, (d.layers[top]?.name ?? "BASE").toUpperCase(), `WPM ${this.wpm()}`];
    }
    return out;
  }

  private build(): SimSnapshot {
    const layers = this.activeLayers();
    return {
      t: this.t,
      phase: this.phase,
      flash: this.flash,
      layers,
      topLayer: layers.at(-1) ?? 0,
      pressed: [...this.held.keys()],
      mods: this.activeMods(),
      text: this.text,
      hid: this.hid.slice(),
      console: this.log.slice(),
      profile: this.profile,
      hostConnected: this.hostConnected,
      peripheralConnected: this.peripheralConnected,
      battery: { ...this.battery },
      wpm: this.wpm(),
      environment: this.environment,
      reading: this.reading,
      encoderValue: this.encoderValue,
      screens: this.screens(),
      revision: this.revision,
    };
  }
}

export function describe(b: Binding): string {
  switch (b.kind) {
    case "kp":
      return `&kp ${b.key}`;
    case "mo":
    case "to":
    case "tog":
      return `&${b.kind} ${b.layer}`;
    case "lt":
      return `&lt ${b.layer} ${b.key}`;
    case "mt":
      return `&mt ${b.mod} ${b.key}`;
    case "bt":
      return `&bt ${b.action}${b.profile !== undefined ? ` ${b.profile}` : ""}`;
    case "out":
      return `&out ${b.action}`;
    case "trans":
      return "&trans";
    case "none":
      return "&none";
    default:
      return b.raw;
  }
}

/** Keycap legend for a binding, given the layer names. */
export function legend(b: Binding, layerNames: string[]): string {
  switch (b.kind) {
    case "kp":
      return keyInfo(b.key).label;
    case "mo":
    case "tog":
    case "to":
      return layerNames[b.layer] ?? `L${b.layer}`;
    case "lt":
      return `${keyInfo(b.key).label}/${layerNames[b.layer] ?? b.layer}`;
    case "mt":
      return `${keyInfo(b.key).label}/${keyInfo(b.mod).label}`;
    case "bt":
      return b.action === "BT_SEL" ? `BT${(b.profile ?? 0) + 1}` : b.action.replace(/^BT_/, "BT ");
    case "out":
      return "Out";
    case "trans":
    case "none":
      return "";
    default:
      return "?";
  }
}
