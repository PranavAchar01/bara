// The play surface: the device's own inputs as controls, and its outputs shown the way the device
// makes them. Which controls exist and how each output shows comes from the engine's surface spec
// (always real inputs and outputs of the build); the person can hide, reorder and rename them, set
// sensor values, and ask the agent to change the surface. Nothing here looks at what kind of
// device it is.
import { useEffect, useRef, useState, type PointerEvent as RPointerEvent, type ReactNode } from "react";
import type { InputAction, SimEvent, SimSnap, Surface } from "./remote";
import { groupRows, move, rename, setHidden, setValue, withUnit, type Layout, type Row } from "./surface";

export type Act = (id: string, a: InputAction, v?: number | boolean) => void;

interface PanelProps {
  title: string;
  mode: string;
  surface: Surface;
  rows: Row[];
  layout: Layout;
  setLayout: (l: Layout) => void;
  snap: SimSnap | null;
  act: Act;
  busy: boolean;
  onReset: () => void;
  onChecks: () => void;
  onAsk: (text: string) => Promise<string>;
}

export function PlayPanel(p: PanelProps) {
  const [edit, setEdit] = useState(false);
  const [msg, setMsg] = useState("");
  const [reply, setReply] = useState<string | null>(null);
  const [asking, setAsking] = useState(false);
  const shown = p.rows.filter((r) => edit || !r.hidden);
  // the y axis of a stick is drawn with its x axis, so it gets no row of its own
  const paired = new Set(shown.filter((r) => r.control === "stick" && /\.y$/.test(r.input_id) && shown.some((x) => x.input_id === r.input_id.replace(/\.y$/, ".x"))).map((r) => r.input_id));
  const visible = shown.filter((r) => !paired.has(r.input_id));
  const ask = () => {
    const text = msg.trim();
    if (!text || asking) return;
    setAsking(true);
    setMsg("");
    p.onAsk(text)
      .then(setReply)
      .catch((e: Error) => setReply(e.message))
      .finally(() => setAsking(false));
  };
  return (
    <aside className="play-panel" aria-label="Controls">
      <header className="play-head">
        <div>
          <strong className="play-title">{p.title}</strong>
          <div className="play-sub small">{p.mode}</div>
        </div>
        <button type="button" className="play-chip" aria-pressed={edit} onClick={() => setEdit((v) => !v)} title="Show, hide, rename and reorder the controls">
          {edit ? "Done" : "Arrange"}
        </button>
      </header>
      <div className="play-scroll">
        <div className="play-row play-chipset">
          <button type="button" className="play-btn" disabled={p.busy} onClick={p.onReset} title="Load the firmware again and reboot the device">
            Reset
          </button>
          <BootButton act={p.act} />
        </div>
        {visible.length === 0 && <p className="small play-muted">Every control is hidden. Choose Arrange to bring them back.</p>}
        {groupRows(visible).map((g) => (
          <section key={g.group} className={`play-group ${g.rows.length > 2 && g.rows.every((r) => r.control === "button" || r.control === "key") ? "grid" : ""}`} aria-label={g.group}>
            <h3 className="play-group-title">{g.group}</h3>
            {g.rows.map((r) => (
              <ControlRow key={r.input_id} row={r} {...p} edit={edit} pair={p.rows.find((x) => x.input_id === r.input_id.replace(/\.x$/, ".y") && r.input_id.endsWith(".x")) ?? null} />
            ))}
          </section>
        ))}
      </div>
      <footer className="play-foot">
        {reply && <p className="small play-reply">{reply}</p>}
        <form
          className="play-ask"
          onSubmit={(e) => {
            e.preventDefault();
            ask();
          }}
        >
          <input value={msg} onChange={(e) => setMsg(e.target.value)} placeholder="Ask for a change, e.g. add a battery slider" aria-label="Ask the agent to change the controls" />
          <button type="submit" className="play-btn primary" disabled={!msg.trim() || asking}>
            {asking ? "..." : "Ask"}
          </button>
        </form>
        <button type="button" className="play-link small" onClick={p.onChecks}>
          Checks
        </button>
      </footer>
    </aside>
  );
}

function BootButton(props: { act: Act }) {
  const held = useRef(false);
  return (
    <>
      <button
        type="button"
        className="play-btn"
        title="Hold, then press Reset: the chip comes up as a USB drive"
        onPointerDown={() => (held.current = true)}
        onPointerUp={() => (held.current = false)}
        onPointerLeave={() => (held.current = false)}
      >
        Boot (hold)
      </button>
      <button type="button" className="play-btn" title="Restart the chip" onClick={() => props.act("device", "reset", held.current)}>
        Restart
      </button>
    </>
  );
}

type RowProps = PanelProps & { row: Row; edit: boolean; pair: Row | null };

function ControlRow(p: RowProps) {
  const { row, edit, layout, surface, setLayout } = p;
  const ids = p.pair ? [row.input_id, p.pair.input_id] : [row.input_id];
  const [name, setName] = useState(row.label);
  useEffect(() => setName(row.label), [row.label]);
  return (
    <div className={`play-ctl ${row.hidden ? "off" : ""} ${row.isLead ? "lead" : ""}`}>
      <div className="play-ctl-head">
        {edit ? (
          <input
            className="play-name"
            value={name}
            aria-label={`Name of ${row.label}`}
            onChange={(e) => setName(e.target.value)}
            onBlur={() => setLayout(rename(layout, row.input_id, name))}
            onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
          />
        ) : (
          <span className="play-label">{row.label}</span>
        )}
        {edit && (
          <span className="play-tools">
            <button type="button" aria-label="Move up" onClick={() => setLayout(move(layout, surface, row.input_id, -1))}>
              ↑
            </button>
            <button type="button" aria-label="Move down" onClick={() => setLayout(move(layout, surface, row.input_id, 1))}>
              ↓
            </button>
            <button type="button" onClick={() => setLayout(ids.reduce((l, id) => setHidden(l, id, !row.hidden), layout))}>
              {row.hidden ? "Show" : "Hide"}
            </button>
          </span>
        )}
      </div>
      {!row.hidden && <Widget {...p} />}
    </div>
  );
}

function Widget(p: RowProps) {
  const { row, act, snap } = p;
  const closed = snap?.inputs.closed ?? {};
  switch (row.control) {
    case "slider":
      return row.kind === "sensor" ? <SensorSlider {...p} /> : <AxisSlider row={row} act={act} />;
    case "stick":
      return <StickPad x={row} y={p.pair} act={act} />;
    case "knob":
      return (
        <div className="play-knob">
          <button type="button" className="play-btn" onClick={() => act(row.input_id, "turn", -1)} aria-label={`${row.label} anticlockwise`}>
            ↺
          </button>
          <button type="button" className="play-btn" onClick={() => act(row.input_id, "turn", 1)} aria-label={`${row.label} clockwise`}>
            ↻
          </button>
          <button type="button" className="play-btn" onPointerDown={() => act(row.input_id, "press")} onPointerUp={() => act(row.input_id, "release")}>
            Press
          </button>
        </div>
      );
    case "toggle":
      return (
        <button type="button" role="switch" aria-checked={!!closed[row.input_id]} className={`play-switch ${closed[row.input_id] ? "on" : ""}`} onClick={() => act(row.input_id, closed[row.input_id] ? "release" : "press")}>
          <i aria-hidden />
          {closed[row.input_id] ? "On" : "Off"}
        </button>
      );
    default:
      return (
        <button
          type="button"
          className={`play-press ${closed[row.input_id] ? "down" : ""}`}
          onPointerDown={() => act(row.input_id, "press")}
          onPointerUp={() => act(row.input_id, "release")}
          onPointerLeave={() => closed[row.input_id] && act(row.input_id, "release")}
        >
          {row.kind === "key" ? "Press key" : "Press"}
        </button>
      );
  }
}

function SensorSlider(p: RowProps) {
  const { row, layout, setLayout, act } = p;
  const lo = row.min ?? 0;
  const hi = row.max ?? 1;
  const v = layout.values[row.input_id] ?? row.default ?? lo;
  const step = (hi - lo) / 200;
  const timer = useRef<number | null>(null);
  const latest = useRef(layout);
  latest.current = layout;
  useEffect(
    () => () => {
      if (timer.current) window.clearTimeout(timer.current);
    },
    [],
  );
  return (
    <div className="play-slider">
      <input
        type="range"
        min={lo}
        max={hi}
        step={step}
        value={v}
        aria-label={`${row.label}${row.unit ? ` (${row.unit})` : ""}`}
        onChange={(e) => {
          const n = Number(e.target.value);
          setLayout(setValue(latest.current, row, n));
          if (timer.current) window.clearTimeout(timer.current);
          timer.current = window.setTimeout(() => act(row.input_id, "sensor", n), 60);
        }}
      />
      <output className="play-value">{withUnit(row, v)}</output>
    </div>
  );
}

function AxisSlider(props: { row: Row; act: Act }) {
  const { row, act } = props;
  const [v, setV] = useState(0);
  return (
    <div className="play-slider">
      <input
        type="range"
        min={-1}
        max={1}
        step={0.05}
        value={v}
        aria-label={row.label}
        onChange={(e) => {
          setV(Number(e.target.value));
          act(row.input_id, "axis", Number(e.target.value));
        }}
      />
      <output className="play-value">{v.toFixed(2)}</output>
    </div>
  );
}

/** A joystick: drag the dot; it springs back on release. */
function StickPad(props: { x: Row; y: Row | null; act: Act }) {
  const { x, y, act } = props;
  const pad = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<[number, number]>([0, 0]);
  const last = useRef(0);
  const sent = useRef<[number, number]>([0, 0]);
  const send = (nx: number, ny: number, force = false) => {
    setPos([nx, ny]);
    const now = performance.now();
    if (!force && now - last.current < 90) return;
    last.current = now;
    if (Math.abs(nx - sent.current[0]) > 0.01) {
      act(x.input_id, "axis", nx);
      sent.current[0] = nx;
    }
    if (y && Math.abs(ny - sent.current[1]) > 0.01) {
      act(y.input_id, "axis", ny);
      sent.current[1] = ny;
    }
  };
  const move = (e: RPointerEvent) => {
    const r = pad.current?.getBoundingClientRect();
    if (!r || !(e.buttons & 1)) return;
    send(Math.max(-1, Math.min(1, ((e.clientX - r.left) / r.width) * 2 - 1)), Math.max(-1, Math.min(1, -(((e.clientY - r.top) / r.height) * 2 - 1))));
  };
  return (
    <div
      ref={pad}
      className="play-pad"
      role="slider"
      aria-label={`${x.label}${y ? ` and ${y.label}` : ""}`}
      aria-valuenow={pos[0]}
      onPointerDown={(e) => {
        (e.target as HTMLElement).setPointerCapture(e.pointerId);
        move(e);
      }}
      onPointerMove={move}
      onPointerUp={() => send(0, 0, true)}
    >
      <span className="play-pad-dot" style={{ left: `${50 + pos[0] * 42}%`, top: `${50 - pos[1] * 42}%` }} />
    </div>
  );
}

// --- outputs --------------------------------------------------------------------------------

interface DockProps {
  surface: Surface;
  snap: SimSnap | null;
  typed: string;
  lines: { key: number; text: string; tone: string }[];
  tones: number;
  /** Another device's output in the same combined device (CombinedDisplay). */
  children?: ReactNode;
}

/** The device's outputs, each shown the way the surface spec says: lights, a speaker, a motor, text. */
export function OutputsDock(p: DockProps) {
  const leds = p.snap?.leds ?? [];
  const by = (id: string) => leds.find((l) => l.id === id);
  const lights = p.surface.outputs.filter((o) => o.show === "led" || o.show === "led_strip");
  const strip = lights.filter((o) => o.show === "led_strip" || lights.length > 6);
  const singles = lights.filter((o) => !strip.includes(o));
  const buzzers = p.surface.outputs.filter((o) => o.show === "buzzer");
  const motors = p.surface.outputs.filter((o) => o.show === "motor");
  const consoles = p.surface.outputs.some((o) => o.show === "console");
  const hasOutputs = lights.length + buzzers.length + motors.length > 0;
  if (!hasOutputs && !consoles && !p.typed && !p.children) return null;
  return (
    <section className="play-dock" aria-label="Outputs">
      {hasOutputs && (
        <div className="play-outs">
          {singles.map((o) => (
            <span key={o.output_id} className={`play-led ${by(o.output_id)?.on ? "on" : ""}`} title={`${o.label}: ${by(o.output_id)?.on ? "on" : "off"}`}>
              <i aria-hidden />
              {o.label}
            </span>
          ))}
          {strip.length > 0 && (
            <span className="play-strip" aria-label="Light strip">
              {strip.map((o) => (
                <i key={o.output_id} className={by(o.output_id)?.on ? "on" : ""} title={o.label} />
              ))}
            </span>
          )}
          {buzzers.map((o) => (
            <span key={o.output_id} className={`play-buzz ${by(o.output_id)?.on ? "on" : ""}`} title={o.label}>
              <b aria-hidden />
              <b aria-hidden />
              <b aria-hidden />
              {o.label}
            </span>
          ))}
          {motors.map((o) => (
            <span key={o.output_id} className={`play-motor ${by(o.output_id)?.on ? "on" : ""}`} title={o.label}>
              <i aria-hidden />
              {o.label}
            </span>
          ))}
        </div>
      )}
      {p.children}
      {(consoles || p.typed) && <Terminal lines={p.lines} typed={p.typed} powered={!!p.snap?.powered} />}
    </section>
  );
}

function Terminal(props: { lines: { key: number; text: string; tone: string }[]; typed: string; powered: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [props.lines]);
  return (
    <div className="play-term">
      <div className="play-typed" aria-label="What the device typed">
        <span className="play-muted small">typed</span>
        <pre>
          {props.typed}
          <span className="play-caret" aria-hidden />
        </pre>
      </div>
      <div ref={ref} className="play-log" role="log" aria-live="polite">
        {props.lines.length === 0 && <div className="play-muted">{props.powered ? "Operate the device." : "The device is off."}</div>}
        {props.lines.slice(-60).map((l) => (
          <div key={l.key} className={`play-line ${l.tone}`}>
            {l.text}
          </div>
        ))}
      </div>
    </div>
  );
}

/** A short beep through WebAudio each time the firmware drives its buzzer. */
export function useBuzzer(tones: number): void {
  const ctx = useRef<AudioContext | null>(null);
  const seen = useRef(tones);
  useEffect(() => {
    if (tones === seen.current) return;
    seen.current = tones;
    try {
      const Ctor = window.AudioContext;
      ctx.current ??= new Ctor();
      const c = ctx.current;
      if (c.state === "suspended") void c.resume();
      const o = c.createOscillator();
      const g = c.createGain();
      o.type = "square";
      o.frequency.value = 880;
      g.gain.value = 0.04;
      o.connect(g).connect(c.destination);
      o.start();
      o.stop(c.currentTime + 0.09);
    } catch {
      // no audio output on this machine: the buzzer still shows as lit
    }
  }, [tones]);
}

export function toneCount(events: SimEvent[]): number {
  return events.filter((e) => e.type === "tone").length;
}
