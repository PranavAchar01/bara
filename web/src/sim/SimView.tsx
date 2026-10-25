// Simulation mode, played in place. The workspace stays mounted: the same device, materials and
// camera glide into play pose (the viewport's own sim frame), the build-only panels fade away and
// the device powers on where it stands. This file is the layer over it: the engine session (the
// firmware compiled for the build's controller and run in an emulator, or the host harness when the
// chip has no model), the play surface (PlaySurface: only the inputs the device really has, named in
// standard terms, with the outputs shown the way the device makes them) and, behind one small
// control, the checks (tests, firmware, signals, the build agent). Esc leaves; the camera glides back.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useApp } from "../state/store";
import { partRect } from "../three/agentTargets";
import { elementPoses } from "../three/layout";
import type { Build } from "../spec/types";
import { serverUrl } from "../net/mode";
import { setActiveMachine, type DemoMachine } from "./api";
import { deriveInputMap } from "./inputMap";
import { closeSimPanel } from "./simPanelStore";
import { enterBridge, showRemote, simHooks, useSim } from "./simStore";
import { hotspotSlots } from "./SimHotspots";
import { useSimLink } from "./simLink";
import { OutputsDock, PlayPanel, toneCount, useBuzzer } from "./PlaySurface";
import { applyOps, fallbackSurface, loadLayout, resolveRows, saveLayout, type Layout } from "./surface";
import { sim, terminalLine, typedText, type ChatEntry, type InputAction, type SimEvent, type SimSnap, type SimTest, type SimViewData, type Surface } from "./remote";
import "./sim.css";
import "./simulator.css";
import "./play.css";

const TICK_MS = 200;
const FAST_TICK_MS = 90;
const MAX_LINES = 400;

type Line = { key: number; text: string; tone: "out" | "in" | "hid" | "sys" };
type Act = (id: string, a: InputAction, v?: number | boolean) => void;

export function SimView() {
  const build = useApp((s) => s.build);
  useEscape();
  useHashRoute(build?.build_id ?? null);
  if (!build) {
    return (
      <div className="play" role="dialog" aria-label="Simulation">
        <div className="play-loading">Open a build to simulate it.</div>
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

/** The viewport in its operating pose while this layer is open: same device, same materials, case shown. */
function useDeviceStage(build: Build) {
  useEffect(() => enterBridge(build), [build.build_id]); // eslint-disable-line react-hooks/exhaustive-deps
}

function Simulator(props: { build: Build }) {
  const { build } = props;
  const id = build.build_id;
  useDeviceStage(build);
  const map = useMemo(() => deriveInputMap(build), [build]);
  const [data, setData] = useState<SimViewData | null>(null);
  const [snap, setSnap] = useState<SimSnap | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>("Building the firmware");
  const [lines, setLines] = useState<Line[]>([]);
  const [typed, setTyped] = useState("");
  const [tones, setTones] = useState(0);
  const seq = useRef(0);
  const inflight = useRef(false);
  const chain = useRef<Promise<unknown>>(Promise.resolve());
  const subs = useRef(new Set<() => void>());
  const typedAll = useRef("");

  const absorb = useCallback((s: SimSnap | null, reset = false) => {
    if (!s) return;
    if (reset) {
      seq.current = 0;
      typedAll.current = "";
      setLines([]);
      setTyped("");
    }
    const fresh: SimEvent[] = s.events.filter((e) => e.seq > seq.current);
    seq.current = Math.max(seq.current, s.seq);
    setSnap(s);
    const beeps = toneCount(fresh);
    if (beeps) setTones((n) => n + beeps);
    showRemote({ powered: s.powered, bootloader: !!s.bootloader, fb: s.fb ?? null, rows: s.screen });
    if (!fresh.length) return;
    if (fresh.some((e) => e.type === "typed")) {
      typedAll.current = typedText(fresh, typedAll.current);
      setTyped(typedAll.current);
      subs.current.forEach((f) => f());
    }
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

  // one call at a time, in the order they were made: a release can never overtake its press, and a
  // slow answer can never carry a later `since` past events another answer has not delivered yet
  const call = useCallback(
    (fn: () => Promise<SimSnap>, quiet = false) => {
      const next = chain.current
        .then(fn)
        .then((s) => absorb(s))
        .catch((e: Error) => {
          if (!quiet) setError(e.message);
        });
      chain.current = next;
      return next;
    },
    [absorb],
  );
  const act = useCallback<Act>(
    (input, action, value) => {
      void call(() => sim.input(id, { id: input, action, value, since: seq.current }));
    },
    [id, call],
  );

  // the device runs in real time while the screen is open; faster when it draws pixels
  const running = !!data?.snapshot && !busy;
  const fast = !!snap?.fb;
  useEffect(() => {
    if (!running) return;
    let last = performance.now();
    const t = window.setInterval(() => {
      if (inflight.current) return;
      const now = performance.now();
      const ms = Math.min(600, now - last);
      last = now;
      inflight.current = true;
      call(() => sim.run(id, ms, seq.current), true).finally(() => {
        inflight.current = false;
      });
    }, fast ? FAST_TICK_MS : TICK_MS);
    return () => window.clearInterval(t);
  }, [id, running, fast, call]);

  // a click on the 3D model, or a real key, reaches the firmware through here
  useEffect(() => {
    simHooks.press = (i) => act(`${i.instanceId}#${i.index}`, "press");
    simHooks.release = (i) => act(`${i.instanceId}#${i.index}`, "release");
    return () => {
      simHooks.press = simHooks.release = undefined;
    };
  }, [act]);

  // the on-screen bot drives the same device through the same engine
  useEffect(() => {
    if (!data) return;
    const inputs = useSim.getState().map?.inputs ?? [];
    const machine: DemoMachine = {
      keys: () => inputs.map((i, n) => ({ id: `${i.instanceId}#${i.index}`, label: i.name, side: "", pos: n })),
      press: (key) => act(key, "press"),
      release: (key) => act(key, "release"),
      rectOf: (key) => {
        const i = inputs.find((x) => `${x.instanceId}#${x.index}` === key);
        const r = i ? partRect(i.instanceId) : null;
        return r ? new DOMRect(r.x, r.y, r.w, r.h) : null;
      },
      snapshot: () => ({ text: typedAll.current }),
      subscribe: (fn) => {
        subs.current.add(fn);
        return () => subs.current.delete(fn);
      },
    };
    setActiveMachine(machine);
    return () => setActiveMachine(null);
  }, [data, act]);

  const reset = useCallback(() => {
    setBusy("Rebooting");
    sim
      .reset(id)
      .then(adopt)
      .catch((e: Error) => setError(e.message))
      .finally(() => setBusy(null));
  }, [id, adopt]);

  useStageLink(data, snap, act);
  const surface = useSurface(id, data);
  const [layout, setLayoutState] = useState<Layout | null>(null);
  const layoutRef = useRef<Layout | null>(null);
  useEffect(() => {
    if (!surface) return;
    const l = loadLayout(id, surface);
    layoutRef.current = l;
    setLayoutState(l);
  }, [id, surface]);
  const setLayout = useCallback(
    (l: Layout) => {
      layoutRef.current = l;
      setLayoutState(l);
      saveLayout(id, l);
    },
    [id],
  );
  // sensor values the person set earlier go to the device again each time it boots
  useEffect(() => {
    if (!data || !surface) return;
    const l = layoutRef.current ?? loadLayout(id, surface);
    for (const c of surface.controls) {
      const v = l.values[c.input_id];
      if (c.kind === "sensor" && v !== undefined && v !== c.default) act(c.input_id, "sensor", v);
    }
  }, [data, surface, id, act]);
  useBuzzer(tones);

  const ask = useCallback(
    async (text: string): Promise<string> => {
      setBusy("Working");
      try {
        const r = await sim.chat(id, text);
        adopt(r.sim);
        const ops = r.reply.surface_ops ?? [];
        if (ops.length && surface && layoutRef.current) {
          const out = applyOps(layoutRef.current, surface, ops);
          setLayout(out.layout);
          for (const x of out.sensorSets) act(x.id, "sensor", x.value);
        }
        return r.reply.text;
      } finally {
        setBusy(null);
      }
    },
    [id, adopt, surface, setLayout, act],
  );
  const [checks, setChecks] = useState(false);
  const rows = surface && layout ? resolveRows(surface, layout) : [];
  const fw = data?.firmware;
  const mode = fw?.mode === "emulated" ? `Firmware running on an emulated ${fw.board.label}` : fw?.mode === "host" ? `Firmware running in the host harness (no emulator for ${fw.board.label})` : "Not running";
  return (
    <div className="play" role="dialog" aria-label="Simulation">
      <header className="play-bar">
        <span className="play-live" aria-hidden />
        <strong>Simulation</strong>
        <span className="spacer" />
        <button type="button" className="play-btn primary" onClick={closeSimPanel} title="Back to the build (Esc)">
          Back <kbd>Esc</kbd>
        </button>
      </header>
      {error && (
        <div className="play-error" role="alert">
          {error}
          <button type="button" className="play-btn" onClick={() => setError(null)}>
            Dismiss
          </button>
        </div>
      )}
      {!data || !surface || !layout ? (
        <div className="play-loading" role="status">
          <i aria-hidden />
          {busy ? `${busy}...` : "The simulator could not start for this build."}
        </div>
      ) : (
        <>
          <PlayPanel
            title={data.io.device.name ?? "Device"}
            mode={mode}
            surface={surface}
            rows={rows}
            layout={layout}
            setLayout={setLayout}
            snap={snap}
            act={act}
            busy={!!busy}
            onReset={reset}
            onChecks={() => setChecks((v) => !v)}
            onAsk={ask}
          />
          <OutputsDock surface={surface} snap={snap} typed={typed} lines={lines} tones={tones} />
          {checks && (
            <div className="play-checks sx">
              <button type="button" className="play-btn play-checks-x" onClick={() => setChecks(false)}>
                Close
              </button>
              <SidePane id={id} data={data} snap={snap} act={act} setData={setData} adopt={adopt} busy={busy} setBusy={setBusy} />
            </div>
          )}
        </>
      )}
    </div>
  );
}

/** The engine's surface spec for this build, or the one derived from the plan when it cannot be had. */
function useSurface(id: string, data: SimViewData | null): Surface | null {
  const [surface, setSurface] = useState<Surface | null>(null);
  const sig = data ? data.io.inputs.map((i) => i.id).join(",") + "|" + data.io.outputs.map((o) => o.id).join(",") : "";
  useEffect(() => {
    if (!data) return;
    let live = true;
    sim
      .surface(id)
      .then((s) => live && setSurface(s))
      .catch(() => live && setSurface(fallbackSurface(data.io)));
    return () => {
      live = false;
    };
  }, [id, sig]); // eslint-disable-line react-hooks/exhaustive-deps
  return surface;
}

/** Click targets on the model for knobs, sticks, dials and switches live in the workspace canvas; this feeds them. */
function useStageLink(data: SimViewData | null, snap: SimSnap | null, act: Act): void {
  const slots = useMemo(() => {
    if (!data) return [];
    const placed = new Set((useSim.getState().map?.inputs ?? []).map((i) => `${i.instanceId}#${i.index}`));
    const b = useApp.getState().build;
    const power = data.io.power.switch;
    const own = hotspotSlots(data.io.inputs.filter((i) => i.kind !== "key" && i.kind !== "sensor"), placed, null).map((s) => {
      const part = b?.parts.find((p) => p.instance_id === s.instanceId);
      if (!b || !part || part.quantity < 2) return s;
      const layout = (b.layouts ?? []).find((l) => l.layout_id === part.placement.layout_id);
      return { ...s, poses: elementPoses(part.placement, part.quantity, layout).map((e) => [e.position[0], e.position[1], e.position[2]] as [number, number, number]) };
    });
    const pw = power ? hotspotSlots([], placed, { id: power.id, label: power.label, kind: "power", instance_id: power.instance_id }) : [];
    return [...own, ...pw];
  }, [data]);
  const closed = snap?.inputs.closed;
  const powered = !!snap?.powered;
  useEffect(() => {
    useSimLink.setState({ slots, act, closed: closed ?? {}, powered });
  }, [slots, act, closed, powered]);
  useEffect(() => () => useSimLink.setState({ slots: [], act: null, closed: {}, powered: false }), []);
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
    <div className="sx2-waves">
      <div className="sx-muted small">last 2 s, logic level</div>
      {pins.length === 0 ? <span className="small sx-muted">No output pin has changed yet.</span> : <canvas ref={ref} className="sx-wave" width={720} height={34} />}
    </div>
  );
}

// --- right: tests, firmware, the agent and the control list ---------------------------------

const GROUPS: { id: SimTest["group"]; title: string }[] = [
  { id: "firmware", title: "Firmware (build + host unit tests)" },
  { id: "emulation", title: "Chip emulation" },
  { id: "pinmap", title: "Pin plan" },
  { id: "ngspice", title: "Circuit (ngspice)" },
  { id: "kicad", title: "KiCad evaluation (ERC, DRC, board statistics)" },
];

type SideProps = { id: string; data: SimViewData; snap: SimSnap | null; act: Act; setData: (v: SimViewData) => void; adopt: (v: SimViewData) => void; busy: string | null; setBusy: (b: string | null) => void };

function SidePane(props: SideProps) {
  const [tab, setTab] = useState<"tests" | "firmware" | "chat" | "signals">("tests");
  const tabs = [
    ["tests", "Tests"],
    ["firmware", "Firmware"],
    ["chat", "Chat"],
    ["signals", "Signals"],
  ] as const;
  return (
    <aside className="sx2-side" aria-label="Checks">
      <div className="sx-tabs" role="tablist">
        {tabs.map(([k, label]) => (
          <button key={k} type="button" role="tab" aria-selected={tab === k} className={tab === k ? "active" : ""} onClick={() => setTab(k)}>
            {label}
          </button>
        ))}
      </div>
      <div className="sx-side-scroll">
        {tab === "tests" && <Tests {...props} />}
        {tab === "firmware" && <Firmware id={props.id} data={props.data} />}
        {tab === "chat" && <Chat {...props} />}
        {tab === "signals" && <Waves snap={props.snap} />}
      </div>
    </aside>
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
      {t.violations && t.violations.length > 0 && (
        <ul className="sx-violations small">
          {t.violations.slice(0, 40).map((v, n) => (
            <li key={n} className={v.severity ?? ""}>
              <b>{v.severity ?? "note"}</b> {v.description ?? v.type}
            </li>
          ))}
          {t.violations.length > 40 && <li className="sx-muted">and {t.violations.length - 40} more in the log below</li>}
        </ul>
      )}
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