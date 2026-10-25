// Simulation mode, inside the Canvas: the frame driver (cap travel, game time), caps for inputs
// the board model draws itself, and the live picture on the display face.
import { useEffect, useMemo, useRef } from "react";
import { useFrame, useThree, type ThreeEvent } from "@react-three/fiber";
import { Html } from "@react-three/drei";
import * as THREE from "three";
import { useApp } from "../state/store";
import { clearCaps, caps, stepCaps, TRAVEL_MM } from "../sim/press";
import { drawScreen } from "../sim/screenDraw";
import { tick } from "../sim/runtime";
import { pressInput, releaseInput, setHover, useSim } from "../sim/simStore";
import { screenFrame, type SimInput } from "../sim/inputMap";
import { screenSizeMm } from "../sim/view";
import { isDrag } from "./explode";
import { partWorldBox } from "./agentTargets";
import { stage } from "./stage";

/** Pointer handlers shared by instanced parts and cap proxies: press on down, release on up, hover names the input. */
export interface InputHandlers {
  onPointerDown: (e: ThreeEvent<PointerEvent>) => void;
  onPointerUp: (e: ThreeEvent<PointerEvent>) => void;
  onPointerOver: (e: ThreeEvent<PointerEvent>) => void;
  onPointerOut: () => void;
}

const mouseHeld = new Set<string>();
/** A press waits this long for a drag to show itself before the key goes down (a tap goes down on release). */
const PRESS_HOLD_MS = 70;
let pending: { input: SimInput; x: number; y: number; timer: number } | null = null;
let dragWatch: ((e: PointerEvent) => void) | null = null;

function commit(): void {
  if (!pending) return;
  const { input, timer } = pending;
  window.clearTimeout(timer);
  pending = null;
  mouseHeld.add(input.id);
  pressInput(input);
}

function stopDragWatch(): void {
  if (dragWatch) window.removeEventListener("pointermove", dragWatch);
  dragWatch = null;
}

/**
 * Orbit always works: the camera is already turning under the pointer. A drag that starts on a key
 * therefore never presses it, and one that began holding it lets it go once it travels past a few px.
 */
function watchDrag(x: number, y: number): void {
  stopDragWatch();
  dragWatch = (e) => {
    if (!isDrag(e.clientX - x, e.clientY - y)) return;
    if (pending) {
      window.clearTimeout(pending.timer);
      pending = null;
    } else releaseMouse();
    document.body.style.cursor = "";
    stopDragWatch();
  };
  window.addEventListener("pointermove", dragWatch);
}

/** Release everything the mouse is holding (the pointer went up somewhere else). */
export function releaseMouse(): void {
  stopDragWatch();
  if (pending) {
    window.clearTimeout(pending.timer);
    pending = null;
  }
  const { byId } = useSim.getState();
  for (const id of mouseHeld) {
    const input = byId.get(id);
    if (input) releaseInput(input);
  }
  mouseHeld.clear();
}

export function inputHandlers(
  resolve: (e: ThreeEvent<PointerEvent>) => SimInput | null,
): InputHandlers {
  return {
    onPointerDown: (e) => {
      const input = resolve(e);
      if (!input || e.button !== 0) return;
      e.stopPropagation();
      commit();
      pending = { input, x: e.clientX, y: e.clientY, timer: window.setTimeout(commit, PRESS_HOLD_MS) };
      watchDrag(e.clientX, e.clientY);
    },
    onPointerUp: (e) => {
      const input = resolve(e);
      if (!input) return;
      e.stopPropagation();
      if (pending?.input.id === input.id) commit();
      if (mouseHeld.delete(input.id)) releaseInput(input);
      if (!mouseHeld.size && !pending) stopDragWatch();
    },
    onPointerOver: (e) => {
      const input = resolve(e);
      if (!input) return;
      e.stopPropagation();
      document.body.style.cursor = "pointer";
      setHover(input.id);
    },
    onPointerOut: () => {
      document.body.style.cursor = "";
      setHover(null);
    },
  };
}

/** World top of the case (the highest case box under the stage root), or null before it has loaded. */
function caseTop(): number | null {
  const root = stage.root;
  if (!root) return null;
  let top: number | null = null;
  const box = new THREE.Box3();
  root.traverse((o) => {
    const fit = (o.userData as { fit?: string }).fit;
    if (typeof fit !== "string" || !fit.startsWith("case:")) return;
    box.setFromObject(o);
    if (!box.isEmpty())
      top = top === null ? box.max.z : Math.max(top, box.max.z);
  });
  return top;
}

/** Cap travel and game time; keeps the on-demand renderer drawing while anything moves. */
export function SimDriver() {
  const invalidate = useThree((s) => s.invalidate);
  const active = useSim((s) => s.active);
  useEffect(() => useSim.subscribe(() => invalidate()), [invalidate]);
  useEffect(() => {
    if (!active) return;
    // the display's caret blinks and a typed line lands between frames
    const id = window.setInterval(() => invalidate(), 250);
    return () => {
      window.clearInterval(id);
      clearCaps();
      invalidate();
    };
  }, [active, invalidate]);
  useFrame((_, dt) => {
    const { runtime } = useSim.getState();
    if (!runtime) return;
    const moving = stepCaps(dt, performance.now());
    tick(runtime, dt * 1000);
    if (moving || runtime.game.status === "running") invalidate();
  });
  return null;
}

const CAP_COLOR = new THREE.Color("#2b2f36");
const CAP_DOWN = new THREE.Color("#0a6cff");

function nearest(input: SimInput, all: SimInput[]): number {
  let d = Infinity;
  for (const o of all)
    if (o !== input)
      d = Math.min(
        d,
        Math.hypot(o.pos[0] - input.pos[0], o.pos[1] - input.pos[1]),
      );
  return d;
}

const ARROWS: Record<string, string> = {
  UP: "▲",
  DOWN: "▼",
  LEFT: "◀",
  RIGHT: "▶",
};

function capLabel(name: string): string {
  return ARROWS[name] ?? (name.length > 3 ? name.slice(0, 3) : name);
}

function ProxyCap(props: {
  input: SimInput;
  diameter: number;
  top: React.MutableRefObject<number>;
  handlers: InputHandlers;
}) {
  const { input } = props;
  const group = useRef<THREE.Group>(null);
  const mat = useRef<THREE.MeshStandardMaterial>(null);
  useFrame(() => {
    const g = group.current;
    if (!g) return;
    const depth = caps.depth.get(input.pressKey) ?? 0;
    g.position.set(input.pos[0], input.pos[1], props.top.current - depth);
    g.visible = props.top.current > 0;
    mat.current?.color
      .copy(CAP_COLOR)
      .lerp(CAP_DOWN, Math.min(1, depth / TRAVEL_MM));
  });
  const hovered = useSim((s) => s.hover === input.id);
  return (
    <group ref={group}>
      <mesh rotation={[Math.PI / 2, 0, 0]} {...props.handlers} castShadow>
        <cylinderGeometry
          args={[props.diameter / 2, props.diameter / 2, 2.4, 28]}
        />
        <meshStandardMaterial
          ref={mat}
          color={CAP_COLOR}
          roughness={0.55}
          metalness={0.05}
          emissive={hovered ? "#1d4f99" : "#000000"}
        />
      </mesh>
      <Html
        position={[0, 0, 1.3]}
        center
        zIndexRange={[20, 0]}
        style={{ pointerEvents: "none" }}
      >
        <span className="sim-cap-label">{capLabel(input.name)}</span>
      </Html>
    </group>
  );
}

/**
 * Caps for inputs the routed board model already draws (it carries every footprint's own model,
 * so those parts have no mesh of their own to press): a cap in the case opening at each
 * footprint, sized by the spacing around it.
 */
export function SimCaps(props: { covered: Set<string> }) {
  const active = useSim((s) => s.active);
  const map = useSim((s) => s.map);
  const top = useRef(0);
  const invalidate = useThree((s) => s.invalidate);
  const proxies = useMemo(
    () => (map?.inputs ?? []).filter((i) => props.covered.has(i.instanceId)),
    [map, props.covered],
  );
  useFrame(() => {
    if (!active) return;
    const t = caseTop();
    if (t !== null && Math.abs(t - top.current) > 1e-3) {
      top.current = t + 0.3;
      invalidate();
    }
  });
  if (!active) return null;
  return (
    <>
      {proxies.map((p) => {
        return (
          <ProxyCap
            key={p.id}
            input={p}
            diameter={Math.min(9, Math.max(4, nearest(p, proxies) * 0.8))}
            top={top}
            handlers={inputHandlers(() => p)}
          />
        );
      })}
    </>
  );
}

/** The picture on each display part's face: a canvas texture on a plane fitted to the face. */
export function SimScreens() {
  const active = useSim((s) => s.active);
  const map = useSim((s) => s.map);
  const spec = useSim((s) => s.screen);
  const build = useApp((s) => s.build);
  if (!active || !map || !spec) return null;
  return (
    <>
      {map.displays.map((id) => {
        const part = build?.parts.find((p) => p.instance_id === id);
        return part ? <ScreenPlane key={id} instanceId={id} /> : null;
      })}
    </>
  );
}

function ScreenPlane(props: { instanceId: string }) {
  const spec = useSim((s) => s.screen);
  const group = useRef<THREE.Group>(null);
  const mesh = useRef<THREE.Mesh>(null);
  const bezel = useRef<THREE.Mesh>(null);
  const turned = useRef<THREE.Group>(null);
  const drawn = useRef(-1);
  const box = useMemo(() => new THREE.Box3(), []);
  const scale = spec ? Math.max(1, Math.round(320 / spec.w)) : 1;
  const canvas = useMemo(() => {
    const c = document.createElement("canvas");
    c.width = (spec?.w ?? 160) * scale;
    c.height = (spec?.h ?? 120) * scale;
    return c;
  }, [spec, scale]);
  const texture = useMemo(() => {
    const t = new THREE.CanvasTexture(canvas);
    t.colorSpace = THREE.SRGBColorSpace;
    t.minFilter = THREE.LinearFilter;
    return t;
  }, [canvas]);
  useEffect(() => () => texture.dispose(), [texture]);
  const invalidate = useThree((s) => s.invalidate);
  useFrame(() => {
    const { runtime } = useSim.getState();
    const g = group.current;
    if (!g || !spec || !runtime) return;
    const b = partWorldBox(props.instanceId, box);
    g.visible = !!b;
    if (!b) return;
    const flat: [number, number] = [b.max.x - b.min.x, b.max.y - b.min.y];
    let face = flat;
    let angle = 0;
    if (useSim.getState().view.up) {
      // a handheld: the picture stands upright for the person, its top toward the screen's top,
      // never mirrored, fitted inside the panel as measured across and up that view
      const [ux, uy] = screenFrame.up();
      if (Math.abs(ux) > Math.abs(uy)) face = [flat[1], flat[0]];
      angle = Math.atan2(-ux, uy);
    } else if (flat[0] < flat[1] !== spec.w < spec.h) {
      // a landscape panel on a part lying portrait is turned a quarter, as the module sits on the board
      face = [flat[1], flat[0]];
      angle = Math.PI / 2;
    }
    const [w, h] = screenSizeMm(spec, face);
    if (turned.current) turned.current.rotation.z = angle;
    const top = caseTop();
    const z = Math.max(b.max.z, top ?? -Infinity) + 0.2;
    g.position.set((b.min.x + b.max.x) / 2, (b.min.y + b.max.y) / 2, z);
    mesh.current?.scale.set(w, h, 1);
    bezel.current?.scale.set(w + 1.6, h + 1.6, 1);
    const tickKey =
      runtime.version * 1000 + (Math.floor(performance.now() / 500) % 2);
    if (drawn.current !== tickKey) {
      drawn.current = tickKey;
      drawScreen(
        canvas,
        runtime,
        { ...spec, w: canvas.width, h: canvas.height },
        performance.now(),
      );
      texture.needsUpdate = true;
      invalidate();
    }
  });
  return (
    <group ref={group} visible={false}>
      <group ref={turned}>
        <mesh
          ref={bezel}
          position={[0, 0, -0.05]}
          raycast={() => null}
          renderOrder={5}
        >
          <planeGeometry args={[1, 1]} />
          <meshBasicMaterial color="#05070a" toneMapped={false} />
        </mesh>
        <mesh ref={mesh} raycast={() => null} renderOrder={6}>
          <planeGeometry args={[1, 1]} />
          <meshBasicMaterial map={texture} toneMapped={false} />
        </mesh>
      </group>
    </group>
  );
}
