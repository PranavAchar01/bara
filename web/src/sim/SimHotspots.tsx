// Click targets on the 3D device for the controls that are not a key or a button: knobs, joysticks,
// dials, toggle and power switches. Each is an invisible box over the part, so the model itself is
// what the user touches. Keys and buttons already take clicks on their own meshes (three/sim3d).
import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import type { ThreeEvent } from "@react-three/fiber";
import { partWorldBox } from "../three/agentTargets";
import type { InputAction, RemoteInput } from "./remote";

type Act = (id: string, action: InputAction, value?: number | boolean) => void;

export interface Slot {
  instanceId: string;
  inputs: RemoteInput[];
  /** World position of each element of the part (a quantity above one), in element order. */
  poses?: [number, number, number][];
}

/** One hit box: the inputs it drives and, for one element of several, where it sits. */
interface Unit {
  key: string;
  instanceId: string;
  inputs: RemoteInput[];
  at: [number, number, number] | null;
  /** How far apart the elements of the part sit (x, y), mm. */
  spread: [number, number];
}

/**
 * A part with several elements (two sticks) gets one hit box per element: the axes pair up in
 * order (x, y per stick), a button goes with the stick of its order, and anything left over (a
 * switch) stays with the first.
 */
export function unitsOf(slot: Slot): Unit[] {
  const whole: Unit[] = [{ key: slot.instanceId, instanceId: slot.instanceId, inputs: slot.inputs, at: null, spread: [0, 0] }];
  const poses = slot.poses ?? [];
  const axes = slot.inputs.filter((i) => i.kind === "axis");
  const sticks = Math.min(poses.length, Math.floor(axes.length / 2));
  if (sticks < 2) return whole;
  const range = (k: 0 | 1) => Math.max(...poses.map((p) => p[k])) - Math.min(...poses.map((p) => p[k]));
  const buttons = slot.inputs.filter((i) => i.kind === "button");
  const rest = slot.inputs.filter((i) => i.kind !== "axis" && i.kind !== "button");
  return Array.from({ length: sticks }, (_, k) => ({
    key: `${slot.instanceId}#${k}`,
    instanceId: slot.instanceId,
    inputs: [axes[2 * k], axes[2 * k + 1], ...(buttons.length >= sticks ? [buttons[k]] : []), ...(k === 0 ? rest : [])],
    at: poses[k],
    spread: [range(0), range(1)],
  }));
}

/** The controls to give their own hit box: everything the engine lists that the input map does not place as a key or button. */
export function hotspotSlots(inputs: RemoteInput[], placed: Set<string>, powerSwitch: RemoteInput | null): Slot[] {
  const by = new Map<string, RemoteInput[]>();
  for (const i of [...inputs, ...(powerSwitch ? [powerSwitch] : [])]) {
    if (placed.has(i.id)) continue;
    by.set(i.instance_id, [...(by.get(i.instance_id) ?? []), i]);
  }
  return [...by].map(([instanceId, list]) => ({ instanceId, inputs: list }));
}

/** Pixels of drag for a full sweep of a stick or dial, and for one click of a knob. */
const SWEEP_PX = 70;
const DIAL_PX = 140;
const DETENT_PX = 16;

function clamp(v: number): number {
  return Math.max(-1, Math.min(1, v));
}

export function SimHotspots(props: { slots: Slot[]; act: Act; closed: Record<string, boolean>; powered: boolean }) {
  return (
    <>
      {props.slots.flatMap(unitsOf).map((u) => (
        <Hotspot key={u.key} unit={u} act={props.act} closed={props.closed} powered={props.powered} />
      ))}
    </>
  );
}

function Hotspot(props: { unit: Unit; act: Act; closed: Record<string, boolean>; powered: boolean }) {
  const { unit: slot, act, closed, powered } = props;
  const [box, setBox] = useState<THREE.Box3 | null>(null);
  const [hot, setHot] = useState(false);
  const drag = useRef<{ x: number; y: number; moved: boolean; dial: number; turned: number } | null>(null);
  const values = useRef<Record<string, number>>({});

  // the part registers a frame or two after the scene mounts
  useEffect(() => {
    let n = 0;
    const find = () => {
      const b = partWorldBox(slot.instanceId, new THREE.Box3());
      if (b) setBox(b);
      else if (n++ < 40) timer = window.setTimeout(find, 250);
    };
    let timer = window.setTimeout(find, 0);
    return () => window.clearTimeout(timer);
  }, [slot.instanceId]);

  const axes = slot.inputs.filter((i) => i.kind === "axis");
  const knob = slot.inputs.find((i) => i.kind === "encoder");
  const press = slot.inputs.find((i) => i.kind === "button");
  const toggle = slot.inputs.find((i) => i.kind === "switch");
  const power = slot.inputs.find((i) => i.kind === "power");
  const live = !!(toggle && closed[toggle.id]) || hot;

  const geometry = useMemo(() => {
    if (!box) return null;
    const size = box.getSize(new THREE.Vector3());
    const centre = box.getCenter(new THREE.Vector3());
    const pad = 1.5;
    if (slot.at) {
      // one element of several: the part's box less the spread of the elements, centred on this one
      const w = Math.max(4, size.x - slot.spread[0]);
      const d = Math.max(4, size.y - slot.spread[1]);
      return { size: [w + pad, d + pad, Math.max(size.z, 1) + pad] as const, centre: [slot.at[0], slot.at[1], centre.z] };
    }
    return { size: [size.x + pad, size.y + pad, Math.max(size.z, 1) + pad] as const, centre: centre.toArray() };
  }, [box, slot]);
  if (!geometry) return null;

  const label = slot.inputs.map((i) => i.label).join(", ");
  const setAxis = (i: RemoteInput, v: number) => {
    if (Math.abs((values.current[i.id] ?? 0) - v) < 0.02) return;
    values.current[i.id] = v;
    act(i.id, "axis", v);
  };

  const down = (e: ThreeEvent<PointerEvent>) => {
    if (e.button !== 0) return;
    e.stopPropagation();
    (e.target as Element).setPointerCapture?.(e.pointerId);
    drag.current = { x: e.clientX, y: e.clientY, moved: false, dial: values.current[axes[0]?.id ?? ""] ?? 0, turned: 0 };
    if (toggle) act(toggle.id, closed[toggle.id] ? "release" : "press");
    if (power) act(power.id, "power", !powered);
  };
  const move = (e: ThreeEvent<PointerEvent>) => {
    const d = drag.current;
    if (!d) return;
    e.stopPropagation();
    const dx = e.clientX - d.x;
    const dy = e.clientY - d.y;
    if (Math.hypot(dx, dy) > 3) d.moved = true;
    if (axes.length >= 2) {
      setAxis(axes[0], clamp(dx / SWEEP_PX));
      setAxis(axes[1], clamp(-dy / SWEEP_PX));
    } else if (axes.length === 1) {
      setAxis(axes[0], clamp(d.dial + dx / DIAL_PX));
    } else if (knob) {
      const steps = Math.trunc(dx / DETENT_PX);
      if (steps !== d.turned) {
        act(knob.id, "turn", steps > d.turned ? 1 : -1);
        d.turned = steps > d.turned ? d.turned + 1 : d.turned - 1;
      }
    }
  };
  const up = (e: ThreeEvent<PointerEvent>) => {
    const d = drag.current;
    drag.current = null;
    if (!d) return;
    e.stopPropagation();
    if (axes.length >= 2) {
      setAxis(axes[0], 0);
      setAxis(axes[1], 0);
      if (!d.moved && press) {
        act(press.id, "tap");
      }
    } else if (knob && !d.moved) {
      if (press) act(press.id, "tap");
      else act(knob.id, "turn", 1);
    }
  };

  return (
    <mesh
      position={geometry.centre as [number, number, number]}
      onPointerDown={down}
      onPointerMove={move}
      onPointerUp={up}
      onPointerCancel={up}
      onWheel={(e) => {
        if (!knob) return;
        e.stopPropagation();
        act(knob.id, "turn", e.deltaY > 0 ? -1 : 1);
      }}
      onPointerOver={(e) => {
        e.stopPropagation();
        document.body.style.cursor = "pointer";
        setHot(true);
      }}
      onPointerOut={() => {
        document.body.style.cursor = "";
        setHot(false);
      }}
      name={`hotspot:${label}`}
    >
      <boxGeometry args={[geometry.size[0], geometry.size[1], geometry.size[2]]} />
      <meshBasicMaterial color="#ffffff" transparent opacity={live ? 0.14 : 0} depthWrite={false} />
    </mesh>
  );
}
