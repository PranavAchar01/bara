// Simulation mode: its own full screen. The engine compiles the build's firmware for its controller
// and runs it in an emulator (or the host test harness, said so plainly when the chip has no
// model). Left: the device, with every input clickable. Center: what the device does (serial
// terminal, display, LEDs, USB reports, pin waveforms). Right: the test catalog (firmware, chip
// emulation, pin plan, ngspice circuit checks) and a chat with the build agent that changes the
// firmware, rebuilds it and re-runs the tests. Esc leaves.
import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent as RPointerEvent } from "react";
import { Canvas } from "@react-three/fiber";
import { Html, OrbitControls } from "@react-three/drei";
import { useApp } from "../state/store";
import { DeviceScene } from "../three/Viewport3D";
import { studioPalette } from "../three/studio";
import type { Build } from "../spec/types";
import { serverUrl } from "../net/mode";
import { deriveInputMap, type SimInput } from "./inputMap";
import { drawOled } from "./oled";
import { closeSimPanel } from "./simPanelStore";
import { sim, terminalLine, type ChatEntry, type InputAction, type RemoteInput, type SimSnap, type SimTest, type SimViewData } from "./remote";
import "./sim.css";
import "./simulator.css";

const TICK_MS = 200;
const MAX_LINES = 400;

type Line = { key: number; text: string; tone: "out" | "in" | "hid" | "sys" };

export function SimView() {
  const build = useApp((s) => s.build);
  useEscape();
  useHashRoute(build?.build_id ?? null);
  if (!build) {
    return (
      <div className="sim" role="dialog" aria-label="Simulation">
        <Bar data={null} busy={false} onReset={() => undefined} />
        <div className="sim-empty">Open a build to simulate it.</div>
      </div>
    );
  }
  return <Simulator key={build.build_id} build={build} />;
}

function useEscape() {
  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.preventDefault();
      e.stopImmediatePropagation();
      closeSimPanel();
    };
    window.addEventListener("keydown", down, true);
    return () => window.removeEventListener("keydown", down, true);
  }, []);
}

/** The screen has its own address (#/sim/<build>) so Back leaves it like any page. */
function useHashRoute(buildId: string | null) {
  useEffect(() => {
    if (!buildId || typeof window === "undefined") return;
    const want = `#/sim/${buildId}`;
    const before = window.location.hash;
    if (before !== want) window.history.pushState(null, "", want);
    const onPop = () => {
      if (!window.location.hash.startsWith("#/sim/")) closeSimPanel();
    };
    window.addEventListener("popstate", onPop);
    return () => {
      window.removeEventListener("popstate", onPop);
      if (window.location.hash === want) window.history.replaceState(null, "", before.startsWith("#/sim/") ? " " : before || " ");
    };
  }, [buildId]);
}

function Simulator(props: { build: Build }) {
  const { build } = props;
  const id = build.build_id;
  const map = useMemo(() => deriveInputMap(build), [build]);
  const [data, setData] = useState<SimViewData | null>(null);
  const [snap, setSnap] = useState<SimSnap | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>("Building the firmware");
  const [lines, setLines] = useState<Line[]>([]);
  const seq = useRef(0);
  const inflight = useRef(false);

  const absorb = useCallback((s: SimSnap | null, reset = false) => {
    if (!s) return;
    if (reset) {
      seq.current = 0;
      setLines([]);
    }
    const fresh = s.events.filter((e) => e.seq > seq.current);
    seq.current = Math.max(seq.current, s.seq);
    setSnap(s);
    if (!fresh.length) return;
    setLines((prev) => {
      const add = fresh.flatMap((e) => {
        const l = terminalLine(e);
        return l ? [{ key: e.seq, ...l }] : [];
      });
      const next = prev.concat(add);
      return next.length > MAX_LINES ? next.slice(next.length - MAX_LINES) : next;
    });
  }, []);

  const adopt = useCallback(
    (v: SimViewData) => {
      setData(v);
      absorb(v.snapshot, true);
    },
    [absorb],
  );

  useEffect(() => {
    let live = true;
    setBusy("Building the firmware");
    sim
      .start(id, map)
      .then((v) => live && adopt(v))
      .catch((e: Error) => live && setError(e.message))
      .finally(() => live && setBusy(null));
    return () => {
      live = false;
    };
  }, [id, map, adopt]);

  // the device runs in real time while the screen is open
  const running = !!data?.snapshot && !busy;
  useEffect(() => {
    if (!running) return;
    let last = performance.now();
    const t = window.setInterval(() => {
      if (inflight.current) return;
      const now = performance.now();
      const ms = Math.min(600, now - last);
      last = now;
      inflight.current = true;
      sim
        .run(id, ms, seq.current)
        .then((s) => absorb(s))
        .catch(() => undefined)
        .finally(() => {
          inflight.current = false;
        });
    }, TICK_MS);
    return () => window.clearInterval(t);
  }, [id, running, absorb]);

  const act = useCallback(
    (input: string, action: InputAction, value?: number | boolean) => {
      sim
        .input(id, { id: input, action, value, since: seq.current })
        .then((s) => absorb(s))
        .catch((e: Error) => setError(e.message));
    },
    [id, absorb],
  );

  const reset = useCallback(() => {
    setBusy("Rebooting");
    sim
      .reset(id)
      .then(adopt)
      .catch((e: Error) => setError(e.message))
      .finally(() => setBusy(null));
  }, [id, adopt]);

  return (
    <div className="sim sx" role="dialog" aria-label="Simulation">
      <Bar data={data} busy={!!busy} onReset={reset} />
      {error && (
        <div className="sx-error" role="alert">
          {error}
          <button type="button" className="sim-btn" onClick={() => setError(null)}>
            Dismiss
          </button>
        </div>
      )}
      {!data ? (
        <div className="sim-empty">{busy ? `${busy}…` : "The simulator could not start for this build."}</div>
      ) : (
        <div className="sx-body">
          <DevicePane build={build} map={map} data={data} snap={snap} act={act} />
          <OutputPane data={data} snap={snap} lines={lines} />
          <SidePane id={id} data={data} setData={setData} adopt={adopt} busy={busy} setBusy={setBusy} />
        </div>
      )}
    </div>
  );
}

// --- header ---------------------------------------------------------------------------------

function Bar(props: { data: SimViewData | null; busy: boolean; onReset: () => void }) {
  const d = props.data;
  const fw = d?.firmware;
  const mode =
    fw?.mode === "emulated"
      ? `running on an emulated ${fw.board.label}`
      : fw?.mode === "host"
        ? `host simulation (no emulator for ${fw.board.label})`
        : "not running";
  return (
    <header className="sim-bar">
      <span className="sim-live" aria-hidden />
      <strong>Simulation</strong>
      {d && (
        <span className="sim-bar-meta small">
          {d.io.device.name ?? "Device"} · firmware{" "}
          <span className={`sx-chip ${fw?.status === "ok" ? "ok" : "fail"}`}>{fw?.status === "ok" ? "built" : "build failed"}</span> {mode}
        </span>
      )}
      <span className="spacer" />
      {d && (
        <button type="button" className="sim-btn" disabled={props.busy} onClick={props.onReset} title="Load the firmware again and reboot the device">
          Reboot
        </button>
      )}
      <button type="button" className="sim-btn primary" onClick={closeSimPanel} title="Back to the workspace (Esc)">
        Exit <kbd>Esc</kbd>
      </button>
    </header>
  );
}

// --- left: the device and its controls ------------------------------------------------------

function DevicePane(props: { build: Build; map: ReturnType<typeof deriveInputMap>; data: SimViewData; snap: SimSnap | null; act: (id: string, a: InputAction, v?: number | boolean) => void }) {
  const { data, snap, act } = props;
  const palette = useMemo(() => studioPalette(), []);
  const scene = useMemo(() => <DeviceScene />, []);
  const camera = useMemo(() => frame(props.build), [props.build]);
  const closed = snap?.inputs.closed ?? {};
  const byKey = useMemo(() => new Map(props.map.inputs.map((i) => [`${i.instanceId}#${i.index}`, i])), [props.map]);
  const placed = data.io.inputs.filter((i) => byKey.has(i.id));
  return (
    <section className="sx-pane sx-device" aria-label="Device">
      <div className="sx-stage" style={{ background: palette.background }}>
        <Canvas dpr={[1, 2]} frameloop="demand" camera={{ up: [0, 0, 1], position: camera.position, near: 1, far: 10000, fov: 30 }} gl={{ antialias: true, preserveDrawingBuffer: true }}>
          {scene}
          {placed.map((i) => (
            <Hotspot key={i.id} input={i} at={byKey.get(i.id) as SimInput} down={!!closed[i.id]} act={act} />
          ))}
          <OrbitControls makeDefault target={camera.target} enableDamping dampingFactor={0.12} />
        </Canvas>
        <div className="sx-stage-note small">Click a control on the device or below. Drag to orbit.</div>
      </div>
      <Controls data={data} snap={snap} act={act} />
    </section>
  );
}

function frame(build: Build): { position: [number, number, number]; target: [number, number, number] } {
  const cam = build.scene?.camera;
  if (cam?.position_mm?.length === 3 && cam.target_mm?.length === 3) {
    return { position: cam.position_mm as [number, number, number], target: cam.target_mm as [number, number, number] };
  }
  const bb = build.scene?.assembly_bbox_mm;
  const c: [number, number, number] = bb ? [(bb.min[0] + bb.max[0]) / 2, (bb.min[1] + bb.max[1]) / 2, (bb.min[2] + bb.max[2]) / 2] : [0, 0, 0];
  const span = bb ? Math.max(bb.max[0] - bb.min[0], bb.max[1] - bb.min[1], 40) : 120;
  return { position: [c[0], c[1] - span * 1.6, c[2] + span * 1.4], target: c };
}

function Hotspot(props: { input: RemoteInput; at: SimInput; down: boolean; act: (id: string, a: InputAction, v?: number | boolean) => void }) {
  const { input, at, down, act } = props;
  const toggle = input.kind === "switch";
  return (
    <Html position={[at.pos[0], at.pos[1], at.pos[2] + 6]} center zIndexRange={[20, 0]}>
      <button
        type="button"
        className={`sx-hot ${down ? "down" : ""}`}
        title={input.label}
        aria-pressed={down}
        onPointerDown={(e) => {
          e.stopPropagation();
          if (toggle) act(input.id, down ? "release" : "press");
          else act(input.id, "press");
        }}
        onPointerUp={() => !toggle && act(input.id, "release")}
        onPointerLeave={() => !toggle && down && act(input.id, "release")}
      >
        <span>{short(input.label)}</span>
      </button>
    </Html>
  );
}

function short(label: string): string {
  const s = label.replace(/\b(button|key|switch)\b/gi, "").trim();
  return (s || label).slice(0, 6);
}

function Controls(props: { data: SimViewData; snap: SimSnap | null; act: (id: string, a: InputAction, v?: number | boolean) => void }) {
  const { data, snap, act } = props;
  const io = data.io;
  const closed = snap?.inputs.closed ?? {};
  const groups = useMemo(() => {
    const out = new Map<string, RemoteInput[]>();
    for (const i of io.inputs) {
      const k = i.kind === "axis" ? `axis:${i.instance_id}` : i.kind;
      out.set(k, [...(out.get(k) ?? []), i]);
    }
    return [...out.entries()];
  }, [io.inputs]);
  const sw = io.power.switch;
  return (
    <div className="sx-controls">
      <div className="sx-controls-head">
        <strong>Controls</strong>
        <span className="small sx-muted">{io.labels_by === "ai" ? "named by the build agent" : "named from the parts list"}</span>
      </div>
      {io.try_first && <p className="small sx-try">{io.try_first}</p>}
      {sw && (
        <div className="sx-row">
          <span className="sx-row-label">{sw.label}</span>
          <button type="button" role="switch" aria-checked={!!snap?.powered} className={`sx-toggle ${snap?.powered ? "on" : ""}`} onClick={() => act(sw.id, "power", !snap?.powered)}>
            {snap?.powered ? "On" : "Off"}
          </button>
        </div>
      )}
      {groups.map(([k, items]) =>
        k.startsWith("axis:") ? (
          <AxisControl key={k} items={items} values={snap?.inputs.axes ?? {}} act={act} />
        ) : k === "encoder" ? (
          items.map((i) => (
            <div className="sx-row" key={i.id}>
              <span className="sx-row-label">{i.label}</span>
              <button type="button" className="sim-btn" onClick={() => act(i.id, "turn", -1)} aria-label={`${i.label} anticlockwise`}>
                ↺
              </button>
              <button type="button" className="sim-btn" onClick={() => act(i.id, "turn", 1)} aria-label={`${i.label} clockwise`}>
                ↻
              </button>
              <button type="button" className="sim-btn" onPointerDown={() => act(i.id, "press")} onPointerUp={() => act(i.id, "release")} title="Press the knob">
                press
              </button>
            </div>
          ))
        ) : (
          <div className="sx-grid" key={k}>
            {items.map((i) =>
              i.kind === "switch" ? (
                <button key={i.id} type="button" role="switch" aria-checked={!!closed[i.id]} className={`sx-key ${closed[i.id] ? "down" : ""}`} onClick={() => act(i.id, closed[i.id] ? "release" : "press")}>
                  {i.label} <span className="sx-muted">{closed[i.id] ? "on" : "off"}</span>
                </button>
              ) : (
                <button
                  key={i.id}
                  type="button"
                  className={`sx-key ${closed[i.id] ? "down" : ""}`}
                  onPointerDown={() => act(i.id, "press")}
                  onPointerUp={() => act(i.id, "release")}
                  onPointerLeave={() => closed[i.id] && act(i.id, "release")}
                  title={i.pin ? `${i.label} on ${i.pin}` : i.label}
                >
                  {i.label}
                </button>
              ),
            )}
          </div>
        ),
      )}
      {io.unsimulated.length > 0 && <p className="small sx-muted">Not simulated: {io.unsimulated.map((u) => u.label).join(", ")}.</p>}
    </div>
  );
}

/** A joystick (two axes on one part) is a pad you drag; a single axis (dial, slider) is a slider. */
function AxisControl(props: { items: RemoteInput[]; values: Record<string, number>; act: (id: string, a: InputAction, v?: number) => void }) {
  const { items, act } = props;
  const pad = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<[number, number]>([0, 0]);
  const last = useRef(0);
  const sent = useRef<[number, number]>([0, 0]);
  if (items.length < 2) {
    const i = items[0];
    return (
      <div className="sx-row">
        <span className="sx-row-label">{i.label}</span>
        <input type="range" min={-1} max={1} step={0.05} defaultValue={0} onChange={(e) => act(i.id, "axis", Number(e.target.value))} aria-label={i.label} />
      </div>
    );
  }
  const [x, y] = items;
  const send = (nx: number, ny: number, force = false) => {
    setPos([nx, ny]);
    const now = performance.now();
    if (!force && now - last.current < 90) return;
    last.current = now;
    // only the axis that moved: a sideways drag must not report "Y moved to 0.00" every step
    if (Math.abs(nx - sent.current[0]) > 0.01) {
      act(x.id, "axis", nx);
      sent.current[0] = nx;
    }
    if (Math.abs(ny - sent.current[1]) > 0.01) {
      act(y.id, "axis", ny);
      sent.current[1] = ny;
    }
  };
  const move = (e: RPointerEvent) => {
    const r = pad.current?.getBoundingClientRect();
    if (!r || !(e.buttons & 1)) return;
    const nx = Math.max(-1, Math.min(1, ((e.clientX - r.left) / r.width) * 2 - 1));
    const ny = Math.max(-1, Math.min(1, -(((e.clientY - r.top) / r.height) * 2 - 1)));
    send(nx, ny);
  };
  return (
    <div className="sx-row sx-joy">
      <span className="sx-row-label">
        {x.label} / {y.label}
        <span className="sx-muted small">
          {" "}
          {pos[0].toFixed(2)}, {pos[1].toFixed(2)}
        </span>
      </span>
      <div
        ref={pad}
        className="sx-pad"
        role="slider"
        aria-label={`${x.label} and ${y.label}`}
        aria-valuenow={pos[0]}
        onPointerDown={(e) => {
          (e.target as HTMLElement).setPointerCapture(e.pointerId);
          move(e);
        }}
        onPointerMove={move}
        onPointerUp={() => send(0, 0, true)}
      >
        <span className="sx-pad-dot" style={{ left: `${50 + pos[0] * 42}%`, top: `${50 - pos[1] * 42}%` }} />
      </div>
    </div>
  );
}

// --- center: what the device does -----------------------------------------------------------

function OutputPane(props: { data: SimViewData; snap: SimSnap | null; lines: Line[] }) {
  const { data, snap } = props;
  const display = data.io.outputs.find((o) => o.kind === "display");
  const leds = snap?.leds ?? [];
  const hid = data.io.outputs.find((o) => o.kind === "hid");
  return (
    <section className="sx-pane sx-out" aria-label="Outputs">
      <div className="sx-out-top">
        {display && (
          <div className="sx-card">
            <div className="sx-card-head">{display.label}</div>
            <Screen lines={snap?.powered ? snap.screen : []} />
          </div>
        )}
        <div className="sx-card sx-leds">
          <div className="sx-card-head">Lights and sound</div>
          {leds.length === 0 && <span className="small sx-muted">No LEDs or speaker on this build.</span>}
          {leds.map((l) => (
            <div key={l.id} className="sx-led-row">
              <span className={`sx-led ${l.on ? "on" : ""}`} aria-hidden />
              <span>{l.label}</span>
              <span className="sx-muted small">{l.on ? "on" : "off"}</span>
            </div>
          ))}
          {hid && (
            <>
              <div className="sx-card-head" style={{ marginTop: 10 }}>
                {hid.label}
              </div>
              <code className="sx-hid">{snap?.hid ?? "--"}</code>
            </>
          )}
        </div>
      </div>
      <Terminal lines={props.lines} powered={!!snap?.powered} />
      <Waves snap={snap} />
    </section>
  );
}

function Screen(props: { lines: string[] }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const text = props.lines.join("\n");
  useEffect(() => {
    const c = ref.current;
    const ctx = c?.getContext("2d");
    if (!c || !ctx) return;
    drawOled(ctx, text ? text.split("\n") : [], c.width, c.height);
  }, [text]);
  return <canvas ref={ref} className="sx-screen" width={256} height={128} aria-label={props.lines.join(" / ") || "screen off"} />;
}

function Terminal(props: { lines: Line[]; powered: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [props.lines]);
  return (
    <div className="sx-card sx-term-card">
      <div className="sx-card-head">
        Serial terminal <span className="sx-muted small">115200 baud, from the firmware's UART</span>
      </div>
      <div ref={ref} className="sx-term" role="log" aria-live="polite">
        {props.lines.length === 0 && <div className="sx-muted">{props.powered ? "Waiting for output…" : "The device is off."}</div>}
        {props.lines.map((l) => (
          <div key={l.key} className={`sx-line ${l.tone}`}>
            {l.text}
          </div>
        ))}
      </div>
    </div>
  );
}

/** The last two seconds of every watched pin as a logic trace. */
function Waves(props: { snap: SimSnap | null }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const snap = props.snap;
  const pins = Object.entries(snap?.wave ?? {});
  useEffect(() => {
    const c = ref.current;
    const ctx = c?.getContext("2d");
    if (!c || !ctx || !snap) return;
    const w = c.width;
    const rowH = 34;
    c.height = Math.max(rowH, pins.length * rowH);
    const css = getComputedStyle(c);
    ctx.clearRect(0, 0, w, c.height);
    const t1 = snap.t_ms;
    const t0 = t1 - 2000;
    const labelW = 150;
    pins.forEach(([, p], row) => {
      const y0 = row * rowH + 8;
      ctx.fillStyle = css.getPropertyValue("--sx-muted") || "#8b8f97";
      ctx.font = "11px ui-monospace, Menlo, monospace";
      ctx.fillText(p.name.slice(0, 22), 4, y0 + 14);
      ctx.strokeStyle = css.getPropertyValue("--sx-wave") || "#4cc38a";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      const x = (t: number) => labelW + ((Math.max(t0, t) - t0) / (t1 - t0)) * (w - labelW - 4);
      const yOf = (lvl: number) => (lvl ? y0 : y0 + 18);
      const edges = p.edges;
      let lvl = 0;
      for (const [t, l] of edges) if (t <= t0) lvl = l;
      ctx.moveTo(x(t0), yOf(lvl));
      for (const [t, l] of edges) {
        if (t <= t0) continue;
        ctx.lineTo(x(t), yOf(lvl));
        lvl = l;
        ctx.lineTo(x(t), yOf(lvl));
      }
      ctx.lineTo(x(t1), yOf(lvl));
      ctx.stroke();
    });
  }, [snap, pins]);
  return (
    <div className="sx-card">
      <div className="sx-card-head">
        Pin waveforms <span className="sx-muted small">last 2 s, logic level</span>
      </div>
      {pins.length === 0 ? <span className="small sx-muted">No output pin has changed yet.</span> : <canvas ref={ref} className="sx-wave" width={720} height={34} />}
    </div>
  );
}

// --- right: tests, firmware and the agent ---------------------------------------------------

const GROUPS: { id: SimTest["group"]; title: string }[] = [
  { id: "firmware", title: "Firmware (build + host unit tests)" },
  { id: "emulation", title: "Chip emulation" },
  { id: "pinmap", title: "Pin plan" },
  { id: "ngspice", title: "Circuit (ngspice)" },
];

function SidePane(props: { id: string; data: SimViewData; setData: (v: SimViewData) => void; adopt: (v: SimViewData) => void; busy: string | null; setBusy: (b: string | null) => void }) {
  const [tab, setTab] = useState<"tests" | "firmware">("tests");
  return (
    <section className="sx-pane sx-side" aria-label="Tests and agent">
      <div className="sx-tabs" role="tablist">
        <button type="button" role="tab" aria-selected={tab === "tests"} className={tab === "tests" ? "active" : ""} onClick={() => setTab("tests")}>
          Tests
        </button>
        <button type="button" role="tab" aria-selected={tab === "firmware"} className={tab === "firmware" ? "active" : ""} onClick={() => setTab("firmware")}>
          Firmware
        </button>
      </div>
      <div className="sx-side-scroll">{tab === "tests" ? <Tests {...props} /> : <Firmware id={props.id} data={props.data} />}</div>
      <Chat {...props} />
    </section>
  );
}

function Tests(props: { id: string; data: SimViewData; setData: (v: SimViewData) => void; busy: string | null; setBusy: (b: string | null) => void }) {
  const { id, data, setData } = props;
  const [running, setRunning] = useState<Set<string>>(new Set());
  const [open, setOpen] = useState<string | null>(null);
  const run = (ids?: string[]) => {
    const which = new Set(ids ?? data.tests.map((t) => t.id));
    setRunning(which);
    sim
      .tests(id, ids)
      .then((r) => setData(r.sim))
      .catch(() => undefined)
      .finally(() => setRunning(new Set()));
  };
  const counts = data.tests.reduce<Record<string, number>>((m, t) => ({ ...m, [t.status]: (m[t.status] ?? 0) + 1 }), {});
  return (
    <div className="sx-tests">
      <div className="sx-tests-head">
        <span className="small">
          {data.tests.length} tests · {counts.pass ?? 0} pass · {counts.fail ?? 0} fail{counts.warn ? ` · ${counts.warn} warn` : ""}
          {counts.not_run ? ` · ${counts.not_run} not run` : ""}
        </span>
        <button type="button" className="sim-btn primary" disabled={running.size > 0} onClick={() => run()}>
          {running.size > 0 ? "Running…" : "Run all"}
        </button>
      </div>
      {GROUPS.map((g) => {
        const items = data.tests.filter((t) => t.group === g.id);
        if (!items.length) return null;
        return (
          <div key={g.id} className="sx-test-group">
            <div className="sx-group-title">{g.title}</div>
            {items.map((t) => (
              <div key={t.id} className={`sx-test ${t.status}`}>
                <button type="button" className="sx-test-main" onClick={() => setOpen(open === t.id ? null : t.id)} aria-expanded={open === t.id}>
                  <span className={`sx-badge ${running.has(t.id) ? "running" : t.status}`}>{running.has(t.id) ? "…" : badge(t.status)}</span>
                  <span className="sx-test-name">{t.name}</span>
                </button>
                <button type="button" className="sim-btn sx-run" disabled={running.has(t.id)} onClick={() => run([t.id])}>
                  Run
                </button>
                {t.summary && <div className="sx-test-summary small">{t.summary}</div>}
                {open === t.id && <TestDetail t={t} />}
              </div>
            ))}
          </div>
        );
      })}
    </div>
  );
}

function badge(s: SimTest["status"]): string {
  return s === "pass" ? "PASS" : s === "fail" ? "FAIL" : s === "warn" ? "WARN" : s === "skip" ? "SKIP" : s === "unavailable" ? "N/A" : "—";
}

function TestDetail(props: { t: SimTest }) {
  const { t } = props;
  const log = Array.isArray(t.log) ? t.log.join("\n") : (t.log ?? "");
  return (
    <div className="sx-test-detail">
      {t.numbers && Object.keys(t.numbers).length > 0 && (
        <table className="sx-numbers">
          <tbody>
            {Object.entries(t.numbers).map(([k, v]) => (
              <tr key={k}>
                <td>{k.replace(/_/g, " ")}</td>
                <td>{typeof v === "number" ? +v.toPrecision(4) : v}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {t.assumptions && t.assumptions.length > 0 && (
        <ul className="small sx-muted">
          {t.assumptions.map((a) => (
            <li key={a}>{a}</li>
          ))}
        </ul>
      )}
      {log ? <pre className="sx-log">{log}</pre> : t.status === "not_run" ? <span className="small sx-muted">Not run yet.</span> : null}
    </div>
  );
}

function Firmware(props: { id: string; data: SimViewData }) {
  const fw = props.data.firmware;
  const [file, setFile] = useState<string | null>(null);
  const [text, setText] = useState("");
  useEffect(() => {
    if (!file) return;
    sim
      .source(props.id, file)
      .then(setText)
      .catch(() => setText("Could not load the file."));
  }, [props.id, file, fw.target.sha256]);
  const step = (title: string, s: typeof fw.target) => (
    <div className="sx-step">
      <div className="sx-step-head">
        <span className={`sx-badge ${s.status === "ok" ? "pass" : s.status === "failed" ? "fail" : "skip"}`}>{s.status === "ok" ? "OK" : s.status === "failed" ? "FAILED" : "N/A"}</span>
        <strong>{title}</strong>
        {s.seconds !== undefined && <span className="sx-muted small">{s.seconds.toFixed(2)} s</span>}
      </div>
      {s.compiler && <div className="small sx-muted">{s.compiler}</div>}
      {s.size && (
        <div className="small">
          text {s.size.text} B · data {s.size.data} B · bss {s.size.bss} B · loads at {s.load_address}, entry {s.entry}
        </div>
      )}
      {s.command && <pre className="sx-log">$ {s.command}</pre>}
      {s.log && <pre className="sx-log">{s.log}</pre>}
    </div>
  );
  return (
    <div className="sx-fw">
      {step(`Chip build for ${fw.board.label}`, fw.target)}
      {step("Host test build", fw.host)}
      {fw.notes.length > 0 && (
        <ul className="small sx-muted">
          {fw.notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      )}
      <div className="sx-downloads">
        {Object.entries(fw.downloads).map(([name, url]) => (
          <a key={name} className="sim-btn" href={serverUrl(url)} download>
            {name}
          </a>
        ))}
      </div>
      <div className="sx-files">
        {fw.files.map((f) => (
          <button key={f} type="button" className={`sx-file ${file === f ? "active" : ""}`} onClick={() => setFile(file === f ? null : f)}>
            {f}
          </button>
        ))}
      </div>
      {file && <pre className="sx-log sx-source">{text}</pre>}
    </div>
  );
}

function Chat(props: { id: string; data: SimViewData; adopt: (v: SimViewData) => void; busy: string | null; setBusy: (b: string | null) => void }) {
  const { id, data, adopt, setBusy } = props;
  const [msg, setMsg] = useState("");
  const [pending, setPending] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  const history: ChatEntry[] = pending ? [...data.chat, { role: "user", text: pending }] : data.chat;
  useEffect(() => {
    const el = ref.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [history.length]);
  const send = () => {
    const text = msg.trim();
    if (!text || pending) return;
    setMsg("");
    setPending(text);
    setBusy("Changing the firmware");
    sim
      .chat(id, text)
      .then((r) => adopt(r.sim))
      .catch((e: Error) => adopt({ ...data, chat: [...data.chat, { role: "user", text }, { role: "agent", text: e.message }] }))
      .finally(() => {
        setPending(null);
        setBusy(null);
      });
  };
  return (
    <div className="sx-chat">
      <div className="sx-group-title">Ask the build agent</div>
      <div ref={ref} className="sx-chat-log">
        {history.length === 0 && <div className="small sx-muted">Try “make the status LED blink every 200 ms” or “what does the A button do?”. A change rebuilds the firmware and re-runs the tests.</div>}
        {history.map((m, i) => (
          <div key={i} className={`sx-msg ${m.role}`}>
            <div>{m.text}</div>
            {m.role === "agent" && (m.rebuilt || m.tests) && (
              <div className="small sx-muted">
                {m.rebuilt ? `Rebuilt (${m.build_status ?? "?"})` : ""}
                {m.tests ? ` · tests ${m.tests.passed} pass, ${m.tests.failed} fail` : ""}
              </div>
            )}
          </div>
        ))}
        {pending && <div className="sx-msg agent sx-muted sx-pending">Working…</div>}
      </div>
      <form
        className="sx-chat-form"
        onSubmit={(e) => {
          e.preventDefault();
          send();
        }}
      >
        <input value={msg} onChange={(e) => setMsg(e.target.value)} placeholder="Change something or ask a question" aria-label="Message to the build agent" />
        <button type="submit" className="sim-btn primary" disabled={!msg.trim() || !!pending}>
          Send
        </button>
      </form>
    </div>
  );
}
