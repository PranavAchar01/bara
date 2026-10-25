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
/**
 * Modifiers clicked with the mouse stay down until the next key is clicked, as on a phone's
 * keyboard: click Shift, then K, and the firmware sends a capital K. A second click lets one go.
 */
const latched = new Set<string>();
const MODIFIER = /^[LR](SHFT|CTRL|ALT|GUI)$/;

function isModifier(input: SimInput): boolean {
  return !!input.code && MODIFIER.test(input.code);
}

function releaseLatched(): void {
  const { byId } = useSim.getState();
  for (const id of latched) {
    const input = byId.get(id);
    if (input) releaseInput(input);
  }
  latched.clear();
}
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
      if (mouseHeld.delete(input.id)) {
        if (isModifier(input) && !latched.has(input.id)) latched.add(input.id);
        else {
          latched.delete(input.id);
          releaseInput(input);
          if (!isModifier(input)) releaseLatched();
        }
      }
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
      latched.clear();
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
        <span className={input.role === "key" ? "sim-key-legend" : "sim-cap-label"} data-sim-legend={input.name}>
          {input.role === "key" ? input.name.slice(0, 4) : capLabel(input.name)}
        </span>
      </Html>
    </group>
  );
}

/** A key's printed legend, on top of its cap and moving down with it. */
function KeyLegend(props: { input: SimInput }) {
  const { input } = props;
  const group = useRef<THREE.Group>(null);
  const box = useMemo(() => new THREE.Box3(), []);
  useFrame(() => {
    const g = group.current;
    if (!g) return;
    const b = partWorldBox(input.instanceId, box);
    g.visible = !!b;
    if (!b) return;
    const depth = caps.depth.get(input.pressKey) ?? 0;
    g.position.set(input.pos[0], input.pos[1], b.max.z + 0.2 - depth);
  });
  const down = useSim((s) => !!s.runtime?.held.has(input.id));
  return (
    <group ref={group}>
      <Html center zIndexRange={[20, 0]} style={{ pointerEvents: "none" }}>
        <span className={`sim-key-legend ${down ? "down" : ""}`} data-sim-legend={input.name}>
          {input.name.length > 4 ? input.name.slice(0, 4) : input.name}
        </span>
      </Html>
    </group>
  );
}

/** Legends on a keyboard's keys, so every key can be found and clicked. */
export function SimKeyLegends(props: { covered: Set<string> }) {
  const active = useSim((s) => s.active);
  const map = useSim((s) => s.map);
  // keys the board model draws get a cap of their own, which carries the label
  const keys = useMemo(() => (map?.inputs ?? []).filter((i) => i.role === "key" && !props.covered.has(i.instanceId)), [map, props.covered]);
  if (!active || !keys.length) return null;
  return (
    <>
      {keys.map((k) => (
        <KeyLegend key={k.id} input={k} />
      ))}
    </>
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
    () => (map?.inputs ?? []).filter((i) => props.covered.has(i.instanceId) && !i.spare),
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

/** Canvas pixels for a picture of this many mm: the long side near 480 px, steps of 8 so a resize is rare. */
function canvasSize(w: number, h: number): [number, number] {
  const k = 480 / Math.max(w, h, 1e-3);
  return [Math.max(8, Math.round((w * k) / 8) * 8), Math.max(8, Math.round((h * k) / 8) * 8)];
}

function ScreenPlane(props: { instanceId: string }) {
  const spec = useSim((s) => s.screen);
  const group = useRef<THREE.Group>(null);
  const mesh = useRef<THREE.Mesh>(null);
  const mat = useRef<THREE.MeshBasicMaterial>(null);
  const bezel = useRef<THREE.Mesh>(null);
  const turned = useRef<THREE.Group>(null);
  const drawn = useRef(-1);
  const box = useMemo(() => new THREE.Box3(), []);
  // the canvas follows the picture's shape, so the firmware's frame fills the whole face
  const surface = useRef<{ canvas: HTMLCanvasElement; texture: THREE.CanvasTexture } | null>(null);
  useEffect(() => () => surface.current?.texture.dispose(), []);
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
    const handheld = !!useSim.getState().view.up;
    if (handheld) {
      // a handheld: the picture stands upright for the person, its top toward the screen's top,
      // never mirrored, and covers the panel's whole face as measured across and up that view
      const [ux, uy] = screenFrame.up();
      if (Math.abs(ux) > Math.abs(uy)) face = [flat[1], flat[0]];
      angle = Math.atan2(-ux, uy);
    } else if (flat[0] < flat[1] !== spec.w < spec.h) {
      // a landscape panel on a part lying portrait is turned a quarter, as the module sits on the board
      face = [flat[1], flat[0]];
      angle = Math.PI / 2;
    }
    const [w, h] = handheld ? [face[0] * 0.97, face[1] * 0.97] : screenSizeMm(spec, face);
    const [cw, ch] = canvasSize(w, h);
    let cur = surface.current;
    if (!cur || cur.canvas.width !== cw || cur.canvas.height !== ch) {
      cur?.texture.dispose();
      const canvas = document.createElement("canvas");
      canvas.width = cw;
      canvas.height = ch;
      const texture = new THREE.CanvasTexture(canvas);
      texture.colorSpace = THREE.SRGBColorSpace;
      texture.minFilter = THREE.LinearFilter;
      cur = surface.current = { canvas, texture };
      if (mat.current) {
        mat.current.map = texture;
        mat.current.needsUpdate = true;
      }
      drawn.current = -1;
    }
    if (turned.current) turned.current.rotation.z = angle;
    const top = caseTop();
    const z = Math.max(b.max.z, top ?? -Infinity) + 0.2;
    g.position.set((b.min.x + b.max.x) / 2, (b.min.y + b.max.y) / 2, z);
    mesh.current?.scale.set(w, h, 1);
    bezel.current?.scale.set(w + (handheld ? 0.6 : 1.6), h + (handheld ? 0.6 : 1.6), 1);
    const tickKey =
      runtime.version * 1000 + (Math.floor(performance.now() / 500) % 2);
    if (drawn.current !== tickKey) {
      drawn.current = tickKey;
      drawScreen(
        cur.canvas,
        runtime,
        { ...spec, w: cw, h: ch },
        performance.now(),
      );
      cur.texture.needsUpdate = true;
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
          <meshBasicMaterial ref={mat} toneMapped={false} />
        </mesh>
      </group>
    </group>
  );
}
