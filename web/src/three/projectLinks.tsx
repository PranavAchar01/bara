// Links between the devices of a project, drawn in the scene: a cable is a rubber tube that
// sags from one part down towards the floor and up into the other; a radio link is a dashed
// arc over the top with pulses running along it. Ends sit on the linked parts, in the same
// frame as the companion row (the open device at its own origin, the others at their offsets).
import { useEffect, useMemo, useRef } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import { Line } from "@react-three/drei";
import * as THREE from "three";
import type { Build } from "../spec/types";
import { useProject } from "../project/project";
import type { ProjectLink } from "../project/links";

export interface LinkSlot {
  id: string;
  build: Build | null;
  offset: THREE.Vector3;
}

const CABLE = "#2a2c2f";
const WARN = "#c98a1b";

function endPoint(slot: LinkSlot | undefined, instanceId: string): THREE.Vector3 | null {
  const inst = slot?.build?.parts.find((p) => p.instance_id === instanceId);
  if (!slot || !inst) return null;
  const p = inst.placement.position_mm;
  return new THREE.Vector3(p[0], p[1], p[2] + 2).add(slot.offset);
}

export function ProjectLinkLines(props: { slots: LinkSlot[] }) {
  const links = useProject((s) => s.links);
  const bySlot = useMemo(() => new Map(props.slots.map((s) => [s.id, s])), [props.slots]);
  const drawn = links
    .map((l) => ({ l, a: endPoint(bySlot.get(l.a.canvasId), l.a.instanceId), b: endPoint(bySlot.get(l.b.canvasId), l.b.instanceId) }))
    .filter((x): x is { l: ProjectLink; a: THREE.Vector3; b: THREE.Vector3 } => !!x.a && !!x.b);
  return (
    <group>
      {drawn.map(({ l, a, b }) => (l.medium === "wireless" ? <RadioArc key={l.link_id} a={a} b={b} warn={l.status === "warning"} /> : <Cable key={l.link_id} a={a} b={b} warn={l.status === "warning"} />))}
    </group>
  );
}

function Cable(props: { a: THREE.Vector3; b: THREE.Vector3; warn: boolean }) {
  const { a, b } = props;
  const geom = useMemo(() => {
    const floor = 0.8;
    const out = b.clone().sub(a).setZ(0).normalize();
    const drop = (p: THREE.Vector3, dir: number) => p.clone().addScaledVector(out, 6 * dir).setZ(Math.max(floor, p.z - 4));
    const mid = a.clone().lerp(b, 0.5).setZ(floor);
    const curve = new THREE.CatmullRomCurve3([a, drop(a, 1), mid, drop(b, -1), b], false, "centripetal");
    return new THREE.TubeGeometry(curve, 96, 1.3, 10, false);
  }, [a, b]);
  useEffect(() => () => geom.dispose(), [geom]);
  const mat = useMemo(() => new THREE.MeshPhysicalMaterial({ color: props.warn ? WARN : CABLE, roughness: 0.55, metalness: 0, clearcoat: 0.3, clearcoatRoughness: 0.4 }), [props.warn]);
  useEffect(() => () => mat.dispose(), [mat]);
  return <mesh geometry={geom} material={mat} castShadow raycast={() => null} />;
}

function RadioArc(props: { a: THREE.Vector3; b: THREE.Vector3; warn: boolean }) {
  const { a, b } = props;
  const invalidate = useThree((s) => s.invalidate);
  const curve = useMemo(() => {
    const top = Math.max(a.z, b.z) + Math.max(25, a.distanceTo(b) * 0.28);
    const mid = a.clone().lerp(b, 0.5).setZ(top);
    return new THREE.QuadraticBezierCurve3(a, mid, b);
  }, [a, b]);
  const points = useMemo(() => curve.getPoints(64), [curve]);
  const dots = useRef<(THREE.Mesh | null)[]>([]);
  const reduced = typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
  useFrame(({ clock }) => {
    // pulses travel both ways, like a pairing that talks back
    dots.current.forEach((m, i) => {
      if (!m) return;
      const t = (clock.elapsedTime * 0.35 + i / 3) % 1;
      m.position.copy(curve.getPoint(i % 2 ? 1 - t : t));
      const s = Math.sin(t * Math.PI);
      m.scale.setScalar(0.6 + 0.6 * s);
    });
    if (!reduced) invalidate();
  });
  const color = props.warn ? WARN : "#2f55d4";
  return (
    <group>
      <Line points={points} color={color} lineWidth={1.6} dashed dashSize={3} gapSize={2.5} transparent opacity={0.85} />
      {[0, 1, 2].map((i) => (
        <mesh
          key={i}
          ref={(el) => {
            dots.current[i] = el;
          }}
          raycast={() => null}
        >
          <sphereGeometry args={[1.4, 12, 12]} />
          <meshBasicMaterial color={color} toneMapped={false} />
        </mesh>
      ))}
    </group>
  );
}
