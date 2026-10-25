// Agent-routed boards. While a board routes and its GLB exports it is drawn
// from its record: the outline as a KiCad-look board (mask over FR4) with the
// footprint courtyards in silk, breathing gently so it reads as in progress.
// Footprints hover by testing the pointer ray against one box per footprint
// (the GLB's refdes nodes, else the record's courtyards), never against the
// board mesh, so hover stays cheap on a 500k-vertex board. Clicking a
// footprint that mounts a build part selects that part.
import { useEffect, useMemo, useRef, useState } from "react";
import { useFrame, useThree, type ThreeEvent } from "@react-three/fiber";
import { Html } from "@react-three/drei";
import * as THREE from "three";
import { select } from "../state/store";
import { useSim } from "../sim/simStore";
import type { Board, BoardFootprint, BuildPart } from "../spec/types";
import { courtyard, type HoverBox } from "./boardgeom";

export { footprintBoxes } from "./boardgeom";

let mats: { mask: THREE.MeshPhysicalMaterial; fr4: THREE.MeshStandardMaterial; silk: THREE.LineBasicMaterial } | null = null;
function placeholderMats() {
  if (!mats) {
    // KiCad's default board colours (green mask, FR4 edge, white silk), as the GLB will show them.
    mats = {
      mask: new THREE.MeshPhysicalMaterial({
        color: new THREE.Color("#143323"),
        roughness: 0.45,
        metalness: 0,
        clearcoat: 0.18,
        clearcoatRoughness: 0.35,
        emissive: new THREE.Color("#2e8a52"),
        emissiveIntensity: 0,
      }),
      fr4: new THREE.MeshStandardMaterial({ color: new THREE.Color("#b9a878"), roughness: 0.8, metalness: 0 }),
      silk: new THREE.LineBasicMaterial({ color: new THREE.Color("#f3f3ee"), transparent: true, opacity: 0.85 }),
    };
  }
  return mats;
}

/** The board drawn from its record while there is no GLB: outline, mask, FR4 edge, courtyards. */
export function BoardPlaceholder(props: { board: Board; busy: boolean }) {
  const { board, busy } = props;
  const invalidate = useThree((s) => s.invalidate);
  const m = placeholderMats();
  const thickness = board.thickness_mm ?? 1.6;
  const body = useMemo(() => {
    const pts: number[][] = board.outline_mm?.length
      ? board.outline_mm
      : board.size_mm
        ? [
            [0, 0],
            [board.size_mm[0], 0],
            [board.size_mm[0], -board.size_mm[1]],
            [0, -board.size_mm[1]],
          ]
        : [];
    if (pts.length < 3) return null;
    const shape = new THREE.Shape(pts.map((p) => new THREE.Vector2(p[0], p[1])));
    // Group 0 is the two faces (mask), group 1 the edge (bare FR4).
    return new THREE.ExtrudeGeometry(shape, { depth: thickness, bevelEnabled: false, curveSegments: 24 });
  }, [board.outline_mm, board.size_mm, thickness]);
  const silk = useMemo(() => {
    const seg: number[] = [];
    const z = thickness + 0.03;
    for (const fp of board.footprints ?? []) {
      const pts = courtyard(fp);
      if (!pts) continue;
      for (let i = 0; i < 4; i++) {
        const a = pts[i];
        const b = pts[(i + 1) % 4];
        seg.push(a.x, a.y, z, b.x, b.y, z);
      }
    }
    if (!seg.length) return null;
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(seg, 3));
    return g;
  }, [board.footprints, thickness]);
  useEffect(() => () => body?.dispose(), [body]);
  useEffect(() => () => silk?.dispose(), [silk]);
  useFrame(({ clock }) => {
    // A slow breath on the mask while routing or exporting; off (and no frames asked) when idle.
    const want = busy ? 0.025 + 0.025 * Math.sin(clock.elapsedTime * 2.4) : 0;
    if (Math.abs(m.mask.emissiveIntensity - want) > 1e-3) m.mask.emissiveIntensity = want;
    if (busy) invalidate();
  });
  if (!body) return null;
  return (
    <>
      <mesh geometry={body} material={[m.mask, m.fr4]} castShadow raycast={() => null} />
      {silk && <lineSegments geometry={silk} material={m.silk} raycast={() => null} />}
    </>
  );
}

/** Status pill over a board that is still routing or loading. */
export function BoardStatus(props: { board: Board; text: string }) {
  const at = useMemo(() => {
    const pts = props.board.outline_mm ?? [];
    const c = new THREE.Vector3();
    for (const p of pts) c.add(new THREE.Vector3(p[0], p[1], 0));
    if (pts.length) c.divideScalar(pts.length);
    c.z = (props.board.thickness_mm ?? 1.6) + 6;
    return c;
  }, [props.board.outline_mm, props.board.thickness_mm]);
  return (
    <Html position={at} center zIndexRange={[20, 0]} style={{ pointerEvents: "none" }}>
      <span className="vp-label vp-board-status">{props.text}</span>
    </Html>
  );
}

const _inv = new THREE.Matrix4();
const _ray = new THREE.Ray();
const _hit = new THREE.Vector3();

/**
 * Invisible proxy over the board that resolves the pointer to a footprint and
 * draws its highlight (accent edges, faint fill) and name. Lives in the
 * board's local frame, next to the board meshes.
 */
export function FootprintHover(props: { boxes: HoverBox[]; parts: BuildPart[]; accent: string }) {
  const { boxes, parts, accent } = props;
  const simActive = useSim((s) => s.active);
  const [hover, setHover] = useState<HoverBox | null>(null);
  const proxyRef = useRef<THREE.Mesh>(null);
  const bounds = useMemo(() => {
    const b = new THREE.Box3();
    for (const h of boxes) b.union(h.box);
    return b.isEmpty() ? null : b.expandByScalar(0.5);
  }, [boxes]);
  const proxy = useMemo(() => {
    if (!bounds) return null;
    const size = bounds.getSize(new THREE.Vector3());
    const g = new THREE.BoxGeometry(size.x, size.y, size.z);
    g.translate(...bounds.getCenter(new THREE.Vector3()).toArray());
    return g;
  }, [bounds]);
  useEffect(() => () => proxy?.dispose(), [proxy]);
  useEffect(() => setHover(null), [boxes]);
  const live = useMemo(() => new Set(parts.map((p) => p.instance_id)), [parts]);
  const partName = (fp: BoardFootprint | null) => {
    const p = fp?.instance_id ? parts.find((x) => x.instance_id === fp.instance_id) : undefined;
    return p ? (p.label ?? p.card.display_name) : null;
  };
  const pick = (e: ThreeEvent<PointerEvent | MouseEvent>): HoverBox | null => {
    const mesh = proxyRef.current;
    if (!mesh) return null;
    _inv.copy(mesh.matrixWorld).invert();
    _ray.copy(e.ray).applyMatrix4(_inv);
    // Smallest box the ray passes through: a diode inside a switch courtyard wins.
    let best: HoverBox | null = null;
    let bestVol = Infinity;
    for (const h of boxes) {
      if (!_ray.intersectBox(h.box, _hit)) continue;
      const s = h.box.getSize(_hit);
      const vol = Math.max(s.x, 0.1) * Math.max(s.y, 0.1) * Math.max(s.z, 0.1);
      if (vol < bestVol) {
        bestVol = vol;
        best = h;
      }
    }
    return best;
  };
  const edges = useMemo(() => {
    if (!hover) return null;
    const s = hover.box.getSize(new THREE.Vector3());
    const g = new THREE.EdgesGeometry(new THREE.BoxGeometry(s.x + 0.4, s.y + 0.4, s.z + 0.4));
    return g;
  }, [hover]);
  useEffect(() => () => edges?.dispose(), [edges]);
  // while the device is being operated its parts are controls, not something to inspect
  if (!proxy || simActive) return null;
  const centre = hover ? hover.box.getCenter(new THREE.Vector3()) : null;
  const name = hover ? (partName(hover.footprint) ?? hover.footprint?.label ?? null) : null;
  // The KiCad footprint only when it says more than the name (labels often are the footprint).
  const lib = hover?.footprint?.lib_id?.split(":").pop() ?? null;
  const libNote = lib && lib !== name ? lib : null;
  return (
    <>
      <mesh
        ref={proxyRef}
        geometry={proxy}
        onPointerMove={(e) => {
          const h = pick(e);
          if (h?.ref !== hover?.ref) setHover(h);
          if (h) e.stopPropagation();
          document.body.style.cursor = h && h.footprint?.instance_id && live.has(h.footprint.instance_id) ? "pointer" : "";
        }}
        onPointerOut={() => {
          setHover(null);
          document.body.style.cursor = "";
        }}
        onClick={(e) => {
          const h = pick(e);
          const id = h?.footprint?.instance_id;
          if (id && live.has(id)) {
            e.stopPropagation();
            select(id);
          }
        }}
      >
        <meshBasicMaterial visible={false} />
      </mesh>
      {hover && centre && edges && (
        <group position={centre}>
          <lineSegments geometry={edges} raycast={() => null}>
            <lineBasicMaterial color={accent} transparent opacity={0.95} depthTest={false} toneMapped={false} />
          </lineSegments>
          <mesh raycast={() => null} renderOrder={2}>
            <boxGeometry args={hover.box.getSize(new THREE.Vector3()).addScalar(0.4).toArray()} />
            <meshBasicMaterial color={accent} transparent opacity={0.12} depthWrite={false} toneMapped={false} />
          </mesh>
          <Html position={[0, 0, hover.box.getSize(new THREE.Vector3()).z / 2 + 2]} center zIndexRange={[30, 0]} style={{ pointerEvents: "none" }}>
            <span className="vp-label vp-footprint">
              <b>{hover.ref}</b>
              {name ? ` · ${name}` : ""}
              {libNote ? <span className="vp-footprint-lib">{libNote}</span> : null}
            </span>
          </Html>
        </group>
      )}
    </>
  );
}
