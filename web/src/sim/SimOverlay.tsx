// Simulation mode, over the viewport: the keyboard listeners, the terminal a typing device echoes
// into, the event strip of a handheld, and the name of the input under the pointer.
import { useEffect, useRef, useState } from "react";
import { useApp } from "../state/store";
import { releaseMouse } from "../three/sim3d";
import type { SimInput } from "./inputMap";
import { inputForKey } from "./physical";
import { exitSimulation, pressInput, releaseInput, useSim } from "./simStore";
import "../styles/sim.css";

function editable(t: EventTarget | null): boolean {
  return t instanceof HTMLElement && (t.isContentEditable || /^(input|textarea|select)$/i.test(t.tagName));
}

function Keys() {
  useEffect(() => {
    const down = new Map<string, SimInput>();
    const onDown = (e: KeyboardEvent) => {
      if (editable(e.target)) return;
      const { active, map } = useSim.getState();
      if (!active || !map) return;
      if (e.code === "Escape") {
        e.preventDefault();
        exitSimulation();
        return;
      }
      // browser and OS shortcuts (Cmd+R, Ctrl+L) stay theirs; a bare modifier is still a key of the device
      const bareModifier = /^(Meta|Control|Alt|Shift)(Left|Right)$/.test(e.code);
      if ((e.metaKey || e.ctrlKey) && !bareModifier) return;
      const input = inputForKey(e.code, map.inputs);
      if (!input) return;
      e.preventDefault();
      if (e.repeat || down.has(e.code)) return;
      down.set(e.code, input);
      pressInput(input);
    };
    const onUp = (e: KeyboardEvent) => {
      const input = down.get(e.code);
      if (!input) return;
      down.delete(e.code);
      releaseInput(input);
    };
    const onBlur = () => {
      for (const input of down.values()) releaseInput(input);
      down.clear();
      releaseMouse();
    };
    window.addEventListener("keydown", onDown);
    window.addEventListener("keyup", onUp);
    window.addEventListener("blur", onBlur);
    window.addEventListener("pointerup", releaseMouse);
    window.addEventListener("pointercancel", releaseMouse);
    return () => {
      window.removeEventListener("keydown", onDown);
      window.removeEventListener("keyup", onUp);
      window.removeEventListener("blur", onBlur);
      window.removeEventListener("pointerup", releaseMouse);
      window.removeEventListener("pointercancel", releaseMouse);
      onBlur();
    };
  }, []);
  // a different build on the stage ends the simulation
  const buildId = useApp((s) => s.build?.build_id ?? null);
  const first = useRef(buildId);
  useEffect(() => {
    if (buildId !== first.current) exitSimulation();
  }, [buildId]);
  return null;
}

function Terminal() {
  useSim((s) => s.version);
  const rt = useSim((s) => s.runtime);
  const source = useSim((s) => s.map?.source);
  const text = rt?.terminal.text ?? "";
  const lines = text.split("\n");
  return (
    <div className="sim-terminal" role="log" aria-label="Terminal">
      <div className="sim-term-bar">
        <span className="sim-dots" aria-hidden>
          <i />
          <i />
          <i />
        </span>
        <span className="sim-term-title">terminal</span>
        <span className="sim-term-note">{source === "keymap" ? "typed through the generated keymap" : "simulated"}</span>
      </div>
      <div className="sim-term-body">
        <div className="sim-term-text">
          {lines.map((l, i) => (
            <div key={i} className="sim-term-line">
              {i === 0 && <span className="sim-prompt">$ </span>}
              {l}
              {i === lines.length - 1 && <span className="sim-caret" />}
              {!l && i !== lines.length - 1 && "​"}
            </div>
          ))}
          {!text && <div className="sim-term-hint">Press a key on the keyboard.</div>}
        </div>
      </div>
    </div>
  );
}

function Strip() {
  useSim((s) => s.version);
  const rt = useSim((s) => s.runtime);
  const events = rt?.events ?? [];
  return (
    <div className="sim-strip" role="log" aria-label="Input events">
      <span className="sim-strip-label">inputs</span>
      <span className="sim-strip-events">
        {events.length === 0 && <span className="sim-strip-empty">press a button</span>}
        {events.slice(-8).map((name, i, all) => (
          <b key={`${events.length - all.length + i}`} className={i === all.length - 1 ? "latest" : ""}>
            {name}
          </b>
        ))}
      </span>
    </div>
  );
}

function Hover() {
  const id = useSim((s) => s.hover);
  const input = useSim((s) => (s.hover ? (s.byId.get(s.hover) ?? null) : null));
  const layer = useRef<HTMLDivElement>(null);
  const [at, setAt] = useState<{ x: number; y: number } | null>(null);
  useEffect(() => {
    if (!id) return;
    const move = (e: PointerEvent) => {
      const r = layer.current?.getBoundingClientRect();
      if (r) setAt({ x: e.clientX - r.left, y: e.clientY - r.top });
    };
    window.addEventListener("pointermove", move);
    return () => window.removeEventListener("pointermove", move);
  }, [id]);
  return (
    <div ref={layer} className="sim-hover-layer">
      {input && at && (
        <span className="sim-hover" style={{ left: at.x + 14, top: at.y - 30 }}>
          {input.name}
          {input.code && <em>&amp;kp {input.code}</em>}
        </span>
      )}
    </div>
  );
}

function Live() {
  const mode = useSim((s) => s.map?.mode);
  return (
    <>
      <Keys />
      {mode === "typing" ? <Terminal /> : <Strip />}
      <Hover />
    </>
  );
}

export function SimOverlay() {
  const active = useSim((s) => s.active);
  return active ? <Live /> : null;
}
