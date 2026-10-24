// Simulation mode: the build's firmware loaded onto the device, full screen, like a slide deck's
// Present. Click keys on the 3D board or type on a real keyboard; the right side shows what the
// host receives, the displays and the device's serial console. Esc leaves.
import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { Canvas, useThree } from "@react-three/fiber";
import { Html, OrbitControls } from "@react-three/drei";
import * as THREE from "three";
import { useApp } from "../state/store";
import { DeviceScene } from "../three/Viewport3D";
import { studioPalette } from "../three/studio";
import { placeholderBox } from "../three/bbox";
import { modelAsset, useModel } from "../three/assets";
import type { Build, BuildPart } from "../spec/types";
import { loadDevice, type SimDevice, type SimKey } from "./device";
import { chordFor } from "./input";
import { SimMachine, describe, legend, type SimSnapshot } from "./machine";
import { codeToKeyName, keyInfo } from "./keys";
import { drawOled } from "./oled";
import { closeSim, useSim } from "./simStore";
import { setActiveMachine } from "./api";
import "./sim.css";

/** Layer the key hit boxes live on: the camera never draws it and the raycaster sees only it. */
const SIM_LAYER = 7;
const DEG = Math.PI / 180;
const TICK_MS = 50;

export function SimView() {
  const build = useApp((s) => s.build);
  const keymap = useSim((s) => s.keymap);
  const [generation, setGeneration] = useState(0);
  const machine = useMemo(() => {
    const d = build ? loadDevice(build, keymap) : null;
    return d ? new SimMachine(d) : null;
    // a reset re-creates the machine from the same firmware
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [build?.firmware, build?.build_id, keymap, generation]);
  useEffect(() => {
    if (!machine) return;
    let last = performance.now();
    const id = window.setInterval(() => {
      const now = performance.now();
      machine.advance(now - last);
      last = now;
    }, TICK_MS);
    return () => window.clearInterval(id);
  }, [machine]);
  if (!build || !machine) {
    return (
      <div className="sim" role="dialog" aria-label="Simulation">
        <SimBar device={null} onReset={() => undefined} />
        <div className="sim-empty">This build has no firmware to load yet.</div>
      </div>
    );
  }
  return <SimRunning build={build} machine={machine} onReset={() => setGeneration((g) => g + 1)} />;
}

function SimRunning(props: { build: Build; machine: SimMachine; onReset: () => void }) {
  const { machine } = props;
  const snap = useSyncExternalStore(machine.subscribe, machine.snapshot);
  useSimKeys(machine);
  useEffect(() => {
    setActiveMachine(machine);
    return () => setActiveMachine(null);
  }, [machine]);
  const palette = useMemo(() => studioPalette(), []);
  // the same element every render: a key press re-renders the panels, not every part of the board
  const scene = useMemo(() => <DeviceScene />, []);
  const top = machine.device.layers[snap.topLayer]?.name;
  return (
    <div className="sim" role="dialog" aria-label="Simulation">
      <SimBar device={machine.device} onReset={props.onReset} />
      <div className="sim-body">
        <div className="sim-stage" style={{ background: palette.background }}>
          <Canvas
            dpr={[1, 2]}
            frameloop="demand"
            camera={{ up: [0, 0, 1], position: [-120, -380, 260], near: 1, far: 10000, fov: 32 }}
            onCreated={({ raycaster }) => raycaster.layers.set(SIM_LAYER)}
            gl={{ antialias: true, preserveDrawingBuffer: true }}
          >
            {scene}
            <SimLayer build={props.build} machine={machine} snap={snap} />
            <OrbitControls makeDefault enableDamping dampingFactor={0.12} />
          </Canvas>
          <div className="sim-stage-top">
            <PhaseChip snap={snap} device={machine.device} />
            {machine.device.kind === "keyboard" && top && (
              <span className="sim-chip" title="Highest active layer">
                Layer {snap.topLayer}: {top}
              </span>
            )}
            {snap.mods.length > 0 && <span className="sim-chip accent">{snap.mods.join(" + ")}</span>}
          </div>
          {snap.flash && <FlashCard snap={snap} />}
          <div className="sim-hint small">
            {machine.device.kind === "keyboard" ? "Click keys on the board or type on your keyboard. Drag to orbit." : "Change the room with the sliders; the firmware reads it on its own schedule."} Esc exits.
          </div>
        </div>
        <SimSide machine={machine} snap={snap} />
      </div>
    </div>
  );
}

function SimBar(props: { device: SimDevice | null; onReset: () => void }) {
  const fileRef = useRef<HTMLInputElement>(null);
  const keymap = useSim((s) => s.keymap);
  const d = props.device;
  const onFile = async (f: File | undefined) => {
    if (!f) return;
    useSim.setState({ keymap: { path: f.name, content: await f.text() } });
  };
  return (
    <header className="sim-bar">
      <span className="sim-live" aria-hidden />
      <strong>Simulation</strong>
      {d && (
        <span className="sim-bar-meta small" title={d.name}>
          {d.framework.toUpperCase()} firmware{d.targets.length ? ` on ${d.targets.map((t) => t.label).join(" + ")}` : ""}
          {d.keymapPath && (
            <>
              {" · "}
              <span className="mono">{d.keymapPath}</span>
              {d.keymapSource === "default" ? " (stub, default keymap)" : ""}
            </>
          )}
        </span>
      )}
      <span className="spacer" />
      {d?.kind === "keyboard" && (
        <>
          <input
            ref={fileRef}
            type="file"
            accept=".keymap,.c,.h,.dtsi,.txt"
            hidden
            onChange={(e) => {
              void onFile(e.target.files?.[0]);
              e.target.value = "";
            }}
          />
          {keymap ? (
            <button type="button" className="sim-btn" onClick={() => useSim.setState({ keymap: null })} title="Go back to the build's own keymap">
              Use build keymap
            </button>
          ) : null}
          <button type="button" className="sim-btn" onClick={() => fileRef.current?.click()} title="Load a ZMK .keymap or QMK keymap.c onto the same hardware">
            Load keymap…
          </button>
        </>
      )}
      {d && (
        <button type="button" className="sim-btn" onClick={props.onReset} title="Flash the firmware again and reboot">
          Reflash
        </button>
      )}
      <button type="button" className="sim-btn primary" onClick={closeSim} title="Back to the workspace (Esc)">
        Exit <kbd>Esc</kbd>
      </button>
    </header>
  );
}

function PhaseChip(props: { snap: SimSnapshot; device: SimDevice }) {
  const { snap, device } = props;
  const label =
    snap.phase === "flashing"
      ? "Flashing"
      : snap.phase === "booting"
        ? "Booting"
        : snap.phase === "idle"
          ? "Idle, display off"
          : snap.phase === "asleep"
            ? "Asleep"
            : device.kind === "keyboard"
              ? snap.hostConnected
                ? device.targets.length > 1 && !snap.peripheralConnected
                  ? "Host connected, right half linking"
                  : "Connected to host"
                : "Advertising"
              : "Running";
  return <span className={`sim-chip ${snap.phase === "running" && (snap.hostConnected || device.kind === "gadget") ? "ok" : ""}`}>{label}</span>;
}

function FlashCard(props: { snap: SimSnapshot }) {
  const f = props.snap.flash;
  if (!f) return null;
  return (
    <div className="sim-flash" role="status">
      <div className="small">Loading firmware onto {f.target}</div>
      <div className="sim-bar-track">
        <div className="sim-bar-fill" style={{ width: `${Math.round(f.fraction * 100)}%` }} />
      </div>
    </div>
  );
}

// --- keyboard input ----------------------------------------------------------------------

function useSimKeys(machine: SimMachine) {
  useEffect(() => {
    const held = new Map<string, string[]>();
    const inField = (t: EventTarget | null) => {
      const el = t as HTMLElement | null;
      return !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT");
    };
    const down = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopImmediatePropagation();
        closeSim();
        return;
      }
      if (inField(e.target)) return;
      // the simulator owns the keyboard: nothing in the workspace behind it reacts
      e.stopImmediatePropagation();
      if (e.metaKey && e.code !== "MetaLeft" && e.code !== "MetaRight") return; // keep the browser's own shortcuts
      const name = codeToKeyName(e.code);
      if (!name) return;
      e.preventDefault();
      if (e.repeat || held.has(e.code)) return;
      let chord = chordFor(machine.device, name);
      if (!chord) return;
      // a modifier held before the page had focus (or sent only as a flag) still shifts the key
      const heldIds = new Set([...held.values()].flat());
      for (const [flag, mod] of [
        [e.shiftKey, "LSHFT"],
        [e.ctrlKey, "LCTRL"],
        [e.altKey, "LALT"],
      ] as const) {
        const modChord = flag && !keyInfo(name).modifier ? chordFor(machine.device, mod) : null;
        if (modChord && !modChord.some((id) => heldIds.has(id))) chord = [...modChord, ...chord];
      }
      held.set(e.code, chord);
      for (const id of chord) machine.press(id);
    };
    const up = (e: KeyboardEvent) => {
      if (inField(e.target)) return;
      e.stopImmediatePropagation();
      const chord = held.get(e.code);
      if (!chord) return;
      held.delete(e.code);
      for (const id of [...chord].reverse()) machine.release(id);
    };
    const blur = () => {
      held.clear();
      machine.releaseAll();
    };
    window.addEventListener("keydown", down, true);
    window.addEventListener("keyup", up, true);
    window.addEventListener("blur", blur);
    return () => {
      window.removeEventListener("keydown", down, true);
      window.removeEventListener("keyup", up, true);
      window.removeEventListener("blur", blur);
    };
  }, [machine]);
}

// --- the 3D layer: key hit boxes, pressed keys, legends and live OLEDs ----------------------

function SimLayer(props: { build: Build; machine: SimMachine; snap: SimSnapshot }) {
  const { machine, snap } = props;
  const invalidate = useThree((s) => s.invalidate);
  const controls = useThree((s) => s.controls) as unknown as { enabled: boolean } | null;
  const pressed = useMemo(() => new Set(snap.pressed), [snap.pressed]);
  const layerNames = machine.device.layers.map((l) => l.name);
  useEffect(() => invalidate(), [snap.revision, invalidate]);
  useEffect(() => {
    // a key held with the mouse lets go wherever the pointer is released
    const up = () => {
      for (const id of mouseHeld) machine.release(id);
      mouseHeld.clear();
      if (controls) controls.enabled = true;
    };
    window.addEventListener("pointerup", up);
    return () => window.removeEventListener("pointerup", up);
  }, [machine, controls]);
  const legends = useMemo(
    () => new Map(machine.device.keys.map((k) => [k.id, legend(machine.bindingFor(k.pos), layerNames)])),
    // legends follow the active layers
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [machine, snap.layers.join(",")],
  );
  return (
    <group>
      {machine.device.keys.map((k) => (
        <KeyNode
          key={k.id}
          simKey={k}
          pressed={pressed.has(k.id)}
          legend={legends.get(k.id) ?? ""}
          title={describe(machine.bindingFor(k.pos))}
          onDown={() => {
            if (controls) controls.enabled = false;
            mouseHeld.add(k.id);
            machine.press(k.id);
          }}
        />
      ))}
      {machine.device.displays.map((d) => {
        const part = props.build.parts.find((p) => p.instance_id === d.instanceId);
        return part ? <OledPlane key={d.instanceId} part={part} build={props.build} lines={snap.screens[d.instanceId] ?? []} width={d.width} height={d.height} /> : null;
      })}
    </group>
  );
}

const mouseHeld = new Set<string>();
const hitGeom = new THREE.BoxGeometry(1, 1, 1);
const pressMat = new THREE.MeshBasicMaterial({ color: "#0a6cff", transparent: true, opacity: 0.45, depthWrite: false, toneMapped: false });

function KeyNode(props: { simKey: SimKey; pressed: boolean; legend: string; title: string; onDown: () => void }) {
  const k = props.simKey;
  const pitch = 19.05;
  const w = k.w_u * pitch - 1.5;
  const h = k.h_u * pitch - 1.5;
  const rot: [number, number, number] = [k.rotation[0] * DEG, k.rotation[1] * DEG, (k.rotation[2] + k.yaw) * DEG];
  const [x, y, z] = k.position;
  return (
    <group position={[x, y, z]} rotation={rot}>
      <mesh
        geometry={hitGeom}
        scale={[w, h, 12]}
        position={[0, 0, 5]}
        ref={(m) => {
          m?.layers.set(SIM_LAYER);
        }}
        onPointerDown={(e) => {
          e.stopPropagation();
          props.onDown();
        }}
        onPointerOver={() => (document.body.style.cursor = "pointer")}
        onPointerOut={() => (document.body.style.cursor = "")}
      />
      {props.pressed && <mesh geometry={hitGeom} material={pressMat} scale={[w - 2, h - 2, 9]} position={[0, 0, 3.5]} />}
      {props.legend && (
        <Html position={[0, 0, 11]} center zIndexRange={[10, 0]} style={{ pointerEvents: "none" }}>
          <span className={`sim-legend ${props.pressed ? "down" : ""}`} title={props.title} data-sim-key={k.id}>
            {props.legend}
          </span>
        </Html>
      )}
    </group>
  );
}

function OledPlane(props: { part: BuildPart; build: Build; lines: string[]; width: number; height: number }) {
  const { part, build } = props;
  const invalidate = useThree((s) => s.invalidate);
  const asset = modelAsset(part.assets, false);
  const model = useModel(asset?.url ?? null, false);
  const box = useMemo(() => {
    if (model.status === "ready") {
      const b = model.model.bbox;
      return { min: [b.min.x, b.min.y, b.min.z], max: [b.max.x, b.max.y, b.max.z] };
    }
    return placeholderBox(part, { layouts: build.layouts ?? [], boards: build.boards ?? [], parts: build.parts, catalogBbox: null });
  }, [model, part, build.layouts, build.boards, build.parts]);
  const canvas = useMemo(() => {
    const c = document.createElement("canvas");
    c.width = props.width * 2;
    c.height = props.height * 2;
    return c;
  }, [props.width, props.height]);
  const texture = useMemo(() => {
    const t = new THREE.CanvasTexture(canvas);
    t.colorSpace = THREE.SRGBColorSpace;
    t.magFilter = THREE.NearestFilter;
    return t;
  }, [canvas]);
  useEffect(() => () => texture.dispose(), [texture]);
  const key = props.lines.join("\n");
  useEffect(() => {
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    drawOled(ctx, props.lines, canvas.width, canvas.height);
    texture.needsUpdate = true;
    invalidate();
    // redraw only when the text changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, canvas, texture, invalidate]);
  const p = part.placement.position_mm;
  const bw = box.max[0] - box.min[0];
  const bh = box.max[1] - box.min[1];
  const sw = Math.min(bw * 0.8, bh * 0.8 * (props.width / props.height));
  const sh = sw * (props.height / props.width);
  const cx = (p[0] ?? 0) + (box.min[0] + box.max[0]) / 2;
  const cy = (p[1] ?? 0) + (box.min[1] + box.max[1]) / 2;
  const cz = (p[2] ?? 0) + box.max[2] + 0.25;
  return (
    <mesh position={[cx, cy, cz]} rotation={[0, 0, (part.placement.rotation_deg[2] ?? 0) * DEG]}>
      <planeGeometry args={[sw, sh]} />
      <meshBasicMaterial map={texture} toneMapped={false} />
    </mesh>
  );
}

// --- side panel ----------------------------------------------------------------------------

function SimSide(props: { machine: SimMachine; snap: SimSnapshot }) {
  const { machine, snap } = props;
  const d = machine.device;
  const [tab, setTab] = useState<"serial" | "hid">("serial");
  return (
    <aside className="sim-side" aria-label="Device output">
      {d.kind === "keyboard" && (
        <section className="sim-sec">
          <div className="sim-sec-h">
            <span>Host</span>
            <span className="sim-muted small">
              {snap.hostConnected ? (d.targets.length > 1 || d.framework === "zmk" ? `BLE profile ${snap.profile + 1}` : "USB") : "not connected"}
              {snap.wpm ? ` · ${snap.wpm} WPM` : ""}
            </span>
            <button type="button" className="sim-link small" onClick={() => machine.clearOutput()}>
              Clear
            </button>
          </div>
          <pre className="sim-text" aria-label="What the host receives" aria-live="polite">
            {snap.text}
            <span className="sim-caret" />
          </pre>
        </section>
      )}
      {d.displays.length > 0 && (
        <section className="sim-sec">
          <div className="sim-sec-h">
            <span>Displays</span>
          </div>
          <div className="sim-oleds">
            {d.displays.map((disp) => (
              <OledPanel key={disp.instanceId} label={disp.label} lines={snap.screens[disp.instanceId] ?? []} width={disp.width} height={disp.height} />
            ))}
          </div>
        </section>
      )}
      {(d.sensors.length > 0 || d.encoders.length > 0) && <Controls machine={machine} snap={snap} />}
      <section className="sim-sec grow">
        <div className="sim-sec-h">
          <div className="sim-tabs" role="tablist">
            <button type="button" role="tab" aria-selected={tab === "serial"} className={tab === "serial" ? "active" : ""} onClick={() => setTab("serial")}>
              Serial console
            </button>
            {d.kind === "keyboard" && (
              <button type="button" role="tab" aria-selected={tab === "hid"} className={tab === "hid" ? "active" : ""} onClick={() => setTab("hid")}>
                HID reports
              </button>
            )}
          </div>
        </div>
        <ConsoleLog machine={machine} snap={snap} tab={tab} />
      </section>
    </aside>
  );
}

function OledPanel(props: { label: string; lines: string[]; width: number; height: number }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const key = props.lines.join("\n");
  useEffect(() => {
    const c = ref.current;
    const ctx = c?.getContext("2d");
    if (c && ctx) drawOled(ctx, props.lines, c.width, c.height);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return (
    <figure className="sim-oled">
      <canvas ref={ref} width={props.width * 2} height={props.height * 2} aria-label={`${props.label}: ${props.lines.join(", ") || "off"}`} />
      <figcaption className="small sim-muted">{props.label}</figcaption>
    </figure>
  );
}

function Controls(props: { machine: SimMachine; snap: SimSnapshot }) {
  const { machine, snap } = props;
  const d = machine.device;
  const env = snap.environment;
  return (
    <section className="sim-sec">
      <div className="sim-sec-h">
        <span>Inputs</span>
      </div>
      {d.encoders.map((_, i) => (
        <div key={i} className="sim-row">
          <span className="small">Encoder {i + 1}</span>
          <button type="button" className="sim-btn sm" onClick={() => machine.turnEncoder(i, -1)} aria-label="Turn anticlockwise">
            ⟲
          </button>
          <button type="button" className="sim-btn sm" onClick={() => machine.turnEncoder(i, 1)} aria-label="Turn clockwise">
            ⟳
          </button>
        </div>
      ))}
      {d.sensors.length > 0 && (
        <>
          <Slider label="Temperature" unit="°C" min={-10} max={45} step={0.1} value={env.temperature} onChange={(v) => machine.setEnvironment({ temperature: v })} />
          <Slider label="Humidity" unit="%" min={0} max={100} step={1} value={env.humidity} onChange={(v) => machine.setEnvironment({ humidity: v })} />
          <Slider label="Pressure" unit="hPa" min={950} max={1050} step={0.5} value={env.pressure} onChange={(v) => machine.setEnvironment({ pressure: v })} />
          <p className="small sim-muted">
            Read every {Math.round(d.updateMs / 100) / 10} s{snap.reading ? `; last ${snap.reading.temperature.toFixed(1)} °C` : ""}
          </p>
        </>
      )}
    </section>
  );
}

function Slider(props: { label: string; unit: string; min: number; max: number; step: number; value: number; onChange: (v: number) => void }) {
  return (
    <label className="sim-row">
      <span className="small">{props.label}</span>
      <input type="range" min={props.min} max={props.max} step={props.step} value={props.value} onChange={(e) => props.onChange(Number(e.target.value))} />
      <span className="small mono">
        {props.value.toFixed(props.step < 1 ? 1 : 0)} {props.unit}
      </span>
    </label>
  );
}

function fmtT(ms: number): string {
  return (ms / 1000).toFixed(3).padStart(8, " ");
}

function ConsoleLog(props: { machine: SimMachine; snap: SimSnapshot; tab: "serial" | "hid" }) {
  const ref = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  const rows = props.tab === "serial" ? props.snap.console : props.snap.hid;
  const last = rows.at(-1)?.id;
  useEffect(() => {
    const el = ref.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [last, props.tab]);
  return (
    <div
      ref={ref}
      className="sim-console mono"
      role="log"
      aria-label={props.tab === "serial" ? "Serial console" : "HID reports"}
      onScroll={(e) => {
        const el = e.currentTarget;
        stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
      }}
    >
      {props.tab === "serial"
        ? props.snap.console.map((l) => (
            <div key={l.id} className={`sim-line lv-${l.level}`}>
              <span className="sim-ts">[{fmtT(l.t)}]</span> <span className="sim-src">{l.source}</span> {l.text}
            </div>
          ))
        : props.snap.hid.map((r) => (
            <div key={r.id} className="sim-line">
              <span className="sim-ts">[{fmtT(r.t)}]</span> {r.kind === "consumer" ? "consumer" : r.kind === "down" ? "key down" : "key up  "} {r.key}
              {r.mods.length ? <span className="sim-muted"> (mods {r.mods.join("+")})</span> : null}
            </div>
          ))}
    </div>
  );
}
